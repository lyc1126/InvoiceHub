import json
import runpy
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "src-tauri/icons"


def test_desktop_design_four_is_the_default_native_icon_and_matches_generator():
    config = json.loads((ROOT / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    expected = ["icons/icon.png", "icons/icon.ico", "icons/icon.icns"]
    assert config["bundle"]["icon"] == expected
    for overlay in (ROOT / "src-tauri").glob("tauri.*.conf.json"):
        assert json.loads(overlay.read_text(encoding="utf-8"))["bundle"].get("icon", expected) == expected
    master = Image.open(ICONS / "desktop-04.png")
    regenerated = runpy.run_path(str(ROOT / "scripts/dev/generate_desktop_icon.py"))["render_master"]()
    assert master.size == (1024, 1024)
    assert master.mode == "RGBA"
    assert master.tobytes() == regenerated.tobytes()
    tray = Image.open(ICONS / "icon.png")
    assert tray.size == (512, 512)
    assert tray.mode == "RGBA"
    assert tray.tobytes() == master.resize((512, 512), Image.Resampling.LANCZOS).tobytes()
    assert (ICONS / "icon.png").read_bytes()[24:26] == b"\x08\x06"


def test_native_icon_containers_keep_small_sizes_transparency_and_brand_contrast():
    windows = Image.open(ICONS / "icon.ico")
    assert windows.ico.sizes() == {(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)}
    for size in windows.ico.sizes():
        icon = windows.ico.getimage(size).convert("RGBA")
        pixels = [icon.getpixel((x, y)) for y in range(size[1]) for x in range(size[0])]
        area = size[0] * size[1]
        assert sum(255 - a for r, g, b, a in pixels) / 255 > area * .1
        assert any(g > 180 and r > 120 and b < 180 and a > 240 for r, g, b, a in pixels)
        assert sum(max(r, g, b) < 100 and a > 240 for r, g, b, a in pixels) > area * .08
        assert sum(min(r, g, b) > 220 and a > 240 for r, g, b, a in pixels) > area * .35
    macos = Image.open(ICONS / "icon.icns")
    assert macos.size == (1024, 1024)
    assert macos.convert("RGBA").tobytes() == Image.open(ICONS / "desktop-04.png").tobytes()
