from pathlib import Path

from PIL import Image, ImageOps


BASE_DIR = Path(__file__).resolve().parent
SOURCE = BASE_DIR / "static" / "img" / "bubu-logo.png"
OUTPUT_DIR = BASE_DIR / "static" / "img"

SIZES = {
    "bubu-icon-32.png": 32,
    "bubu-icon-180.png": 180,
    "bubu-icon-192.png": 192,
    "bubu-icon-512.png": 512,
}


def create_icon(source: Path, output: Path, size: int) -> None:
    image = Image.open(source).convert("RGBA")

    # Keep the whole logo visible and make it square.
    image.thumbnail((size, size), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (size, size), (255, 246, 238, 255))

    x = (size - image.width) // 2
    y = (size - image.height) // 2

    canvas.alpha_composite(image, (x, y))
    canvas.save(output, "PNG", optimize=True)


def main() -> None:
    if not SOURCE.exists():
        raise FileNotFoundError(
            f"Logo was not found: {SOURCE}"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for filename, size in SIZES.items():
        output = OUTPUT_DIR / filename
        create_icon(SOURCE, output, size)
        print(f"Created: {output}")


if __name__ == "__main__":
    main()