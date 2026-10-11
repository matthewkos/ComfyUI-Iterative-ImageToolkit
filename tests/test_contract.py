import ast
import json
from pathlib import Path


def test_descriptions_and_meta():
    s = Path("iterative_image_toolkit/nodes.py").read_text()
    t = ast.parse(s)
    for c in (x for x in t.body if isinstance(x, ast.ClassDef) and x.name.startswith("IIT")):
        attrs = {y.id for n in c.body if isinstance(n, ast.Assign) for y in n.targets if isinstance(y, ast.Name)}
        assert {"DESCRIPTION", "OUTPUT_TOOLTIPS"} <= attrs
    assert s.count('"tooltip":') >= 20
    assert s.count('"IIT_META"') >= 2
    assert '"multiline": True' in s


def test_workflow():
    w = json.loads(Path("example_workflows/iit_scale_1mp_text_save.json").read_text())
    assert [x["type"] for x in w["nodes"]] == [
        "IITLoadVersion",
        "ImageScaleToTotalPixels",
        "TextOverlay",
        "IITSaveCandidates",
        "IITViewTrajectory",
    ]
    scale = w["nodes"][1]
    overlay = w["nodes"][2]
    assert scale["widgets_values"] == ["bilinear", 1.0, 1]
    assert overlay["widgets_values"] == ["01-edit/123456789", 5.0, "#ffffff", "top", "left", True]
    assert sum(link[-1] == "IIT_META" for link in w["links"]) == 2
    assert {link[-1] for link in w["links"]} >= {"IMAGE", "MASK", "STRING", "INT", "IIT_META"}


def test_no_custom_step_seed_label_node():
    source = Path("iterative_image_toolkit/nodes.py").read_text()
    assert "IITAddStepSeedLabel" not in source
    assert "IIT Add Step / Seed Label" not in source
