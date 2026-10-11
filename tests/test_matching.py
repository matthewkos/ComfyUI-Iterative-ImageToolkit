import cv2
import numpy as np

from iterative_image_toolkit.matching import locate_crop


def scene(seed=7):
    rng = np.random.default_rng(seed)
    image = np.zeros((700, 900, 3), dtype=np.uint8)
    image[:] = (35, 45, 55)
    for _ in range(180):
        x, y = rng.integers(10, 890), rng.integers(10, 690)
        color = tuple(int(v) for v in rng.integers(40, 255, size=3))
        cv2.circle(image, (int(x), int(y)), int(rng.integers(2, 9)), color, -1)
    cv2.putText(image, "ITERATIVE", (180, 330), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (230, 210, 80), 5)
    return image


def test_locate_crop_with_rotation_scale_and_local_edit():
    a = scene()
    crop = a[180:500, 250:650].copy()
    center = (crop.shape[1] / 2, crop.shape[0] / 2)
    transform = cv2.getRotationMatrix2D(center, 6.0, 0.92)
    b = cv2.warpAffine(crop, transform, (crop.shape[1], crop.shape[0]), borderMode=cv2.BORDER_REFLECT101)
    cv2.rectangle(b, (150, 120), (230, 220), (255, 30, 150), -1)
    result = locate_crop(a, b)
    center_found = result.rotated_bbox["center"]
    assert abs(center_found["x"] - 450) < 45
    assert abs(center_found["y"] - 340) < 45
    assert result.confidence > 0.45
    assert result.aligned_crop.shape[:2] == b.shape[:2]
    assert result.heatmap.shape == b.shape


def test_insufficient_features_fails():
    a = np.zeros((300, 300, 3), dtype=np.uint8)
    b = np.zeros((100, 100, 3), dtype=np.uint8)
    try:
        locate_crop(a, b)
    except ValueError as exc:
        assert "features" in str(exc).lower()
    else:
        raise AssertionError("Expected a feature failure")
