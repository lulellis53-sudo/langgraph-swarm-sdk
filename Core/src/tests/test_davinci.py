"""Offline renderer determinism and scene contract tests."""

import json
from pathlib import Path

import pytest

from langswarm.davinci import DavinciCanvas


def test_sample_scene_renders_deterministically() -> None:
    path = Path(__file__).parents[1] / "examples" / "pixel_scene.json"
    scene = json.loads(path.read_text(encoding="utf-8"))
    first = DavinciCanvas.from_scene(scene).to_svg()
    second = DavinciCanvas.from_scene(scene).to_svg()
    assert first == second
    assert first.startswith("<svg")


def test_polygon_mask_handles_array_comparisons() -> None:
    scene = {
        "canvas": {"width": 8, "height": 8},
        "layers": [
            {
                "primitives": [
                    {
                        "type": "polygon",
                        "points": [[1, 1], [7, 1], [4, 7]],
                        "fill": {"type": "solid", "color": "#ffffff"},
                    }
                ]
            }
        ],
    }
    image = DavinciCanvas.from_scene(scene)
    assert image.palette() == ["#000000", "#ffffff"]


def test_math_expression_rejects_code_execution() -> None:
    scene = {
        "canvas": {"width": 2, "height": 2},
        "math": {"values": {"bad": "=__import__('os').getcwd()"}},
    }
    with pytest.raises(ValueError, match="math expressions"):
        DavinciCanvas.from_scene(scene)


def test_shader_only_change_reuses_geometry_digest() -> None:
    scene = {
        "canvas": {"width": 2, "height": 2},
        "math": {
            "layers": [
                {"primitives": [{"type": "rect", "x": 0, "y": 0, "w": 2, "h": 2, "fill": "$color"}]}
            ]
        },
        "shader": {"fills": {"color": {"type": "solid", "color": "#ff0000"}}},
    }
    art = DavinciCanvas.from_scene(scene)
    digest = art._math_digest
    revised = {**scene, "shader": {"fills": {"color": {"type": "solid", "color": "#00ff00"}}}}
    art.render(revised)
    assert art._math_digest == digest
    assert art.palette() == ["#00ff00"]
