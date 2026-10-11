from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


@dataclass
class MatchResult:
    axis_bbox: dict[str, float]
    rotated_bbox: dict[str, Any]
    aligned_crop: np.ndarray
    confidence: float
    heatmap: np.ndarray
    diagnostics: dict[str, Any]


def _gray(image: np.ndarray) -> np.ndarray:
    rgb = np.clip(image[..., :3], 0, 255).astype(np.uint8)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)


def _features(gray: np.ndarray) -> tuple[list[cv2.KeyPoint], np.ndarray | None, int]:
    if hasattr(cv2, "SIFT_create"):
        detector = cv2.SIFT_create(nfeatures=6000, contrastThreshold=0.02, edgeThreshold=12)
        keypoints, descriptors = detector.detectAndCompute(gray, None)
        return keypoints, descriptors, cv2.NORM_L2
    detector = cv2.ORB_create(nfeatures=6000, scaleFactor=1.15, nlevels=10, fastThreshold=7)
    keypoints, descriptors = detector.detectAndCompute(gray, None)
    return keypoints, descriptors, cv2.NORM_HAMMING


def _ratio_matches(desc_b: np.ndarray, desc_a: np.ndarray, norm: int) -> list[cv2.DMatch]:
    matcher = cv2.BFMatcher(norm)
    pairs = matcher.knnMatch(desc_b, desc_a, k=2)
    threshold = 0.76 if norm == cv2.NORM_L2 else 0.80
    return [first for first, second in pairs if first.distance < threshold * second.distance]


def _valid_fraction(matrix: np.ndarray, width: int, height: int, full_width: int, full_height: int) -> float:
    corners = np.float32([[0, 0], [width, 0], [width, height], [0, height]]).reshape(-1, 1, 2)
    transformed = cv2.transform(corners, matrix).reshape(-1, 2)
    x1, y1 = np.maximum(transformed.min(axis=0), [0, 0])
    x2, y2 = np.minimum(transformed.max(axis=0), [full_width, full_height])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area = max(1.0, float(cv2.contourArea(transformed.astype(np.float32))))
    return float(np.clip(intersection / area, 0.0, 1.0))


def locate_crop(image_a: np.ndarray, image_b: np.ndarray) -> MatchResult:
    if image_a.ndim != 3 or image_b.ndim != 3:
        raise ValueError("A and B must be HxWxC images")
    ha, wa = image_a.shape[:2]
    hb, wb = image_b.shape[:2]
    if hb > ha * 1.5 or wb > wa * 1.5:
        raise ValueError("B must be a crop-scale image relative to A")

    gray_a, gray_b = _gray(image_a), _gray(image_b)
    key_a, desc_a, norm = _features(gray_a)
    key_b, desc_b, _ = _features(gray_b)
    if desc_a is None or desc_b is None or len(key_a) < 4 or len(key_b) < 4:
        raise ValueError("Insufficient image features for crop localization")

    matches = _ratio_matches(desc_b, desc_a, norm)
    if len(matches) < 4:
        raise ValueError(f"Insufficient reliable feature matches: {len(matches)}")

    points_b = np.float32([key_b[item.queryIdx].pt for item in matches]).reshape(-1, 1, 2)
    points_a = np.float32([key_a[item.trainIdx].pt for item in matches]).reshape(-1, 1, 2)
    matrix, inliers = cv2.estimateAffinePartial2D(
        points_b,
        points_a,
        method=cv2.RANSAC,
        ransacReprojThreshold=4.0,
        maxIters=8000,
        confidence=0.995,
        refineIters=20,
    )
    if matrix is None or inliers is None:
        raise ValueError("Could not estimate a translation/scale/rotation transform")

    inlier_mask = inliers.ravel().astype(bool)
    inlier_count = int(inlier_mask.sum())
    if inlier_count < 4:
        raise ValueError(f"Transform has too few inliers: {inlier_count}")

    corners_b = np.float32([[0, 0], [wb - 1, 0], [wb - 1, hb - 1], [0, hb - 1]]).reshape(-1, 1, 2)
    corners_a = cv2.transform(corners_b, matrix).reshape(-1, 2)
    mins = corners_a.min(axis=0)
    maxs = corners_a.max(axis=0)
    x1 = float(np.clip(mins[0], 0, wa - 1))
    y1 = float(np.clip(mins[1], 0, ha - 1))
    x2 = float(np.clip(maxs[0], 0, wa))
    y2 = float(np.clip(maxs[1], 0, ha))
    axis_bbox = {
        "x": x1,
        "y": y1,
        "width": max(0.0, x2 - x1),
        "height": max(0.0, y2 - y1),
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
    }

    scale = float(np.sqrt(matrix[0, 0] ** 2 + matrix[0, 1] ** 2))
    rotation_deg = float(np.degrees(np.arctan2(matrix[1, 0], matrix[0, 0])))
    rotated_bbox = {
        "corners": [{"x": float(x), "y": float(y)} for x, y in corners_a],
        "center": {"x": float(corners_a[:, 0].mean()), "y": float(corners_a[:, 1].mean())},
        "scale": scale,
        "rotation_degrees": rotation_deg,
    }

    aligned_a = cv2.warpAffine(
        image_a[..., :3].astype(np.uint8),
        matrix,
        (wb, hb),
        flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
        borderMode=cv2.BORDER_REFLECT101,
    )
    aligned_gray = cv2.cvtColor(aligned_a, cv2.COLOR_RGB2GRAY)
    original_b_gray = cv2.cvtColor(np.clip(image_b[..., :3], 0, 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
    flow = cv2.calcOpticalFlowFarneback(
        aligned_gray,
        original_b_gray,
        None,
        pyr_scale=0.5,
        levels=4,
        winsize=25,
        iterations=5,
        poly_n=7,
        poly_sigma=1.5,
        flags=cv2.OPTFLOW_FARNEBACK_GAUSSIAN,
    )
    flow_magnitude = cv2.magnitude(flow[..., 0], flow[..., 1])
    edges_a = cv2.Canny(aligned_gray, 60, 160)
    edges_b = cv2.Canny(original_b_gray, 60, 160)
    edge_error = cv2.absdiff(edges_a, edges_b).astype(np.float32) / 255.0
    flow_scale = max(float(np.percentile(flow_magnitude, 95)), 1e-6)
    anomaly = np.clip(0.65 * (flow_magnitude / flow_scale) + 0.35 * edge_error, 0.0, 1.0)
    heat_bgr = cv2.applyColorMap((anomaly * 255).astype(np.uint8), cv2.COLORMAP_TURBO)
    heat_rgb = cv2.cvtColor(heat_bgr, cv2.COLOR_BGR2RGB)

    inlier_ratio = inlier_count / max(len(matches), 1)
    valid_fraction = _valid_fraction(matrix, wb, hb, wa, ha)
    inlier_points = points_b[inlier_mask].reshape(-1, 2)
    if len(inlier_points) >= 3:
        coverage = float(cv2.contourArea(cv2.convexHull(inlier_points)) / max(float(wb * hb), 1.0))
    else:
        coverage = 0.0
    median_flow = float(np.median(flow_magnitude))
    flow_score = float(np.exp(-median_flow / 4.0))
    confidence = float(
        np.clip(
            0.42 * inlier_ratio + 0.20 * min(1.0, coverage * 3.0) + 0.20 * flow_score + 0.18 * valid_fraction,
            0.0,
            1.0,
        )
    )
    diagnostics = {
        "algorithm": "SIFT/ORB + RANSAC similarity transform + Farneback optical-flow refinement",
        "feature_matches": len(matches),
        "inliers": inlier_count,
        "inlier_ratio": inlier_ratio,
        "feature_coverage": coverage,
        "median_flow_pixels": median_flow,
        "valid_crop_fraction": valid_fraction,
        "transform_b_to_a": matrix.tolist(),
        "axis_bbox": axis_bbox,
        "rotated_bbox": rotated_bbox,
        "confidence": confidence,
    }
    return MatchResult(axis_bbox, rotated_bbox, aligned_a, confidence, heat_rgb, diagnostics)


def diagnostics_json(result: MatchResult) -> str:
    return json.dumps(result.diagnostics, ensure_ascii=False, indent=2)
