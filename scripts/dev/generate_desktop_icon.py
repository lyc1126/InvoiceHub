"""Render InvoiceHub desktop design 04 with the bundled OFL brand font.

Run from any directory with the project's Python/Pillow environment.
Native icon files are generated assets; no system fonts or network are used.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
ICON_DIR = ROOT / "src-tauri" / "icons"


def render_master() -> Image.Image:
    size = 2048
    scale = size / 1024
    image = Image.new("RGBA", (size, size))
    draw = ImageDraw.Draw(image)

    def points(values):
        return [tuple(round(v * scale) for v in pair) for pair in values]

    draw.rounded_rectangle(points([(56, 56), (968, 968)]), radius=round(194 * scale), fill="#f8f9f5", outline="#dfe2d7", width=round(3 * scale))
    # A folded paper corner locates the invoice domain without competing with
    # the website wordmark. The compact silhouette also survives tray sizes.
    draw.polygon(points([(748, 105), (920, 277), (787, 277), (748, 238)]), fill="#d9fb5c")
    draw.line(points([(748, 109), (748, 238), (787, 277)]), fill="#b9bfb1", width=round(3 * scale))
    # This fixed Latin wordmark was authored with BASIC shaping. Pillow's
    # optional Raqm changes glyph spacing between Mac/Windows wheels.
    font = ImageFont.truetype(str(ROOT / "website/assets/display.woff"), round(510 * scale),
                              layout_engine=ImageFont.Layout.BASIC)
    bounds = draw.textbbox((0, 0), "hi.", font=font)
    width = bounds[2] - bounds[0]
    left = (size - width) / 2 - bounds[0]
    top = round(340 * scale) - bounds[1]
    draw.text((round(left), top), "hi.", font=font, fill="#242520")
    return image.resize((1024, 1024), Image.Resampling.LANCZOS)


def generate() -> None:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    master = render_master()
    master.save(ICON_DIR / "desktop-04.png", optimize=True)
    # Tauri's tray must receive 8-bit RGBA; keep its established 512px input.
    master.resize((512, 512), Image.Resampling.LANCZOS).save(ICON_DIR / "icon.png", optimize=True)
    master.save(ICON_DIR / "icon.ico", sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
    master.save(ICON_DIR / "icon.icns")
    selectable = ROOT / "web/static/app-icon/website"
    selectable.mkdir(parents=True, exist_ok=True)
    for size in (32, 256):
        master.resize((size, size), Image.Resampling.LANCZOS).save(selectable / f"icon_{size}.png", optimize=True)
    print("Generated desktop-04.png, icon.png, icon.ico and icon.icns")


if __name__ == "__main__":
    generate()
