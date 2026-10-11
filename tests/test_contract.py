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
    w = json.loads(Path("example_workflows/iit_bilinear_scale.json").read_text())
    assert [x["type"] for x in w["nodes"]] == ["IITLoadVersion", "ImageScale", "IITSaveCandidates"]
    assert any(x[-1] == "IIT_META" for x in w["links"])
    assert w["nodes"][1]["widgets_values"][0] == "bilinear"
