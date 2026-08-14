from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from packaging.utils import canonicalize_name, parse_wheel_filename


class DependencyLockError(ValueError):
    pass


def build_lock_text(wheelhouse: Path) -> str:
    wheelhouse = Path(wheelhouse)
    wheels = sorted(wheelhouse.glob("*.whl"), key=lambda item: item.name.casefold())
    if not wheels:
        raise DependencyLockError(f"wheelhouse contains no wheels: {wheelhouse}")

    resolved: dict[str, tuple[str, str, str]] = {}
    for wheel in wheels:
        try:
            raw_name, version, _build, _tags = parse_wheel_filename(wheel.name)
        except Exception as exc:
            raise DependencyLockError(f"invalid wheel filename: {wheel.name}") from exc
        name = canonicalize_name(raw_name)
        version_text = str(version)
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        if name in resolved:
            prior_version, _prior_digest, prior_file = resolved[name]
            raise DependencyLockError(
                f"wheelhouse must contain exactly one wheel per distribution: "
                f"{prior_file} and {wheel.name} both resolve to {name} ({prior_version}, {version_text})"
            )
        resolved[name] = (version_text, digest, wheel.name)

    lines = [
        "# Generated from a platform-specific, binary-only wheelhouse.",
        "# Install with --require-hashes --only-binary=:all: --no-index --find-links=<wheelhouse>.",
    ]
    for name, (version, digest, _filename) in sorted(resolved.items()):
        lines.extend([f"{name}=={version} \\", f"    --hash=sha256:{digest}"])
    return "\n".join(lines) + "\n"


def write_lock(wheelhouse: Path, output: Path) -> Path:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_lock_text(wheelhouse), encoding="utf-8", newline="\n")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a hash lock from a platform-specific wheelhouse")
    parser.add_argument("--wheelhouse", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    write_lock(args.wheelhouse, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
