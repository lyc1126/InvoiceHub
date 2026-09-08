"""Shared allowlist for the bundled official website and its localhost route."""

from pathlib import Path
from shutil import copy2


WEBSITE_ASSETS = (
    "index.html",
    "style.css",
    "app.js",
    "demo-data.js",
    "paper-scene.js",
    "assets/mark.svg",
    "assets/display.woff",
    "assets/OFL-DelaGothicOne.txt",
    "assets/icons.js",
    "assets/LICENSE-lucide",
)
WEBSITE_BUILD_INPUTS = tuple(f"website/{name}" for name in WEBSITE_ASSETS)


def website_asset_path(directory: Path, name: str) -> Path:
    if name not in WEBSITE_ASSETS:
        raise ValueError("Unknown website asset")
    root = directory.resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise FileNotFoundError("Bundled website asset unavailable")
    return path


def copy_website(source_root: Path, destination_root: Path) -> None:
    # HTTP serving, build identity and every assembler use the same list so
    # offline assets cannot be omitted or website maintenance files published.
    sources = [(name, website_asset_path(source_root / "website", name)) for name in WEBSITE_ASSETS]
    for name, source in sources:
        destination = destination_root / "website" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        copy2(source, destination)
