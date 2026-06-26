from pathlib import Path

from PIL import Image, ImageOps


BASE_DIR = Path(__file__).resolve().parent
SOURCE = BASE_DIR / "static" / "img" / "bubu-logo.png"
OUTPUT_DIR = BASE_DIR / "static" / "img"

BACKGROUND = (255, 246, 238, 255)


def build_square_icon(source: Image.Image, size: int, padding_ratio: float = 0.08) -> Image.Image:
    """Create a centered square icon while keeping the whole BUBU logo visible."""
    canvas = Image.new("RGBA", (size, size), BACKGROUND)

    padding = max(1, round(size * padding_ratio))
    target_size = (size - padding * 2, size - padding * 2)

    fitted = ImageOps.contain(
        source.convert("RGBA"),
        target_size,
        method=Image.Resampling.LANCZOS,
    )

    x = (size - fitted.width) // 2
    y = (size - fitted.height) // 2
    canvas.alpha_composite(fitted, (x, y))

    return canvas


def main() -> None:
    if not SOURCE.exists():
        raise FileNotFoundError(
            f"BUBU logo was not found at: {SOURCE}\n"
            "Put your original logo at static/img/bubu-logo.png first."
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    source = Image.open(SOURCE)

    outputs = {
        "bubu-favicon-32.png": 32,
        "bubu-apple-touch-180.png": 180,
        "bubu-icon-192.png": 192,
        "bubu-icon-512.png": 512,
    }

    for filename, size in outputs.items():
        icon = build_square_icon(source, size)
        output = OUTPUT_DIR / filename
        icon.save(output, "PNG", optimize=True)
        print(f"Created {output}")

    ico_source = build_square_icon(source, 256)
    ico_path = OUTPUT_DIR / "favicon.ico"
    ico_source.save(
        ico_path,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Created {ico_path}")


if __name__ == "__main__":
    main()
