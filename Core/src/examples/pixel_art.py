"""Render the sample scene offline: ``uv run python examples/pixel_art.py``."""

from pathlib import Path

import orjson

from langswarm.davinci import DavinciCanvas


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    scene = orjson.loads((root / "examples" / "pixel_scene.json").read_bytes())
    image = DavinciCanvas.from_scene(scene)
    output = root / "data" / "artifacts" / f"{scene['name']}.svg"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(image.to_svg(), encoding="utf-8")
    print(
        f"Rendered {image.width}x{image.height} scene to {output} ({len(image.palette())} colors)."
    )


if __name__ == "__main__":
    main()
