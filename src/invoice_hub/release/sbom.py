from __future__ import annotations

import argparse
import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

from packaging.utils import canonicalize_name

from invoice_hub.version import PRODUCT_NAME, PRODUCT_VERSION, PUBLIC_SOURCE_URL, PYTHON_PACKAGE_VERSION


CYCLONEDX_SPEC_VERSION = "1.6"
LOCK_ENTRY_PATTERN = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\s\\]+)\s*\\?$")
HASH_PATTERN = re.compile(r"^\s*--hash=sha256:(?P<digest>[0-9a-f]{64})\s*\\?$")


class SbomError(ValueError):
    pass


def parse_hash_lock(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.is_file():
        raise SbomError(f"dependency lock does not exist: {path}")
    components: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        entry_match = LOCK_ENTRY_PATTERN.fullmatch(line)
        if entry_match:
            if current is not None and not current["hashes"]:
                raise SbomError(f"lock entry has no SHA-256 at line {line_number}: {current['name']}")
            name = canonicalize_name(entry_match.group("name"))
            current = {"name": name, "version": entry_match.group("version"), "hashes": []}
            components.append(current)
            continue
        hash_match = HASH_PATTERN.fullmatch(line)
        if hash_match and current is not None:
            current["hashes"].append(hash_match.group("digest"))
            continue
        raise SbomError(f"unsupported dependency lock syntax at line {line_number}: {raw_line!r}")
    if not components:
        raise SbomError(f"dependency lock contains no packages: {path}")
    if current is not None and not current["hashes"]:
        raise SbomError(f"lock entry has no SHA-256: {current['name']}")
    names = [component["name"] for component in components]
    if len(names) != len(set(names)):
        raise SbomError("dependency lock contains duplicate distributions")
    return sorted(components, key=lambda item: item["name"])


def build_sbom_payload(dependency_lock: Path, *, target: str) -> dict[str, Any]:
    dependency_lock = Path(dependency_lock)
    dependencies = parse_hash_lock(dependency_lock)
    lock_sha = hashlib.sha256(dependency_lock.read_bytes()).hexdigest()
    product_ref = f"pkg:pypi/invoice-hub@{quote(PYTHON_PACKAGE_VERSION)}"
    components = []
    dependency_refs = []
    for dependency in dependencies:
        purl = f"pkg:pypi/{quote(dependency['name'])}@{quote(dependency['version'])}"
        dependency_refs.append(purl)
        components.append(
            {
                "type": "library",
                "bom-ref": purl,
                "name": dependency["name"],
                "version": dependency["version"],
                "purl": purl,
                "hashes": [{"alg": "SHA-256", "content": digest} for digest in dependency["hashes"]],
            }
        )
    serial = uuid.uuid5(uuid.NAMESPACE_URL, f"{PUBLIC_SOURCE_URL}:{PRODUCT_VERSION}:{target}:{lock_sha}")
    return {
        "bomFormat": "CycloneDX",
        "specVersion": CYCLONEDX_SPEC_VERSION,
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "bom-ref": product_ref,
                "name": PRODUCT_NAME,
                "version": PRODUCT_VERSION,
                "purl": product_ref,
                "licenses": [{"license": {"id": "AGPL-3.0-or-later"}}],
                "externalReferences": [{"type": "vcs", "url": PUBLIC_SOURCE_URL}],
            },
            "properties": [
                {"name": "invoicehub:target", "value": target},
                {"name": "invoicehub:dependency-lock", "value": dependency_lock.name},
                {"name": "invoicehub:dependency-lock-sha256", "value": lock_sha},
            ],
        },
        "components": components,
        "dependencies": [{"ref": product_ref, "dependsOn": dependency_refs}],
    }


def write_sbom(dependency_lock: Path, output: Path, *, target: str) -> Path:
    payload = build_sbom_payload(dependency_lock, target=target)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a deterministic CycloneDX SBOM from an InvoiceHub hash lock")
    parser.add_argument("--dependency-lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target", required=True)
    args = parser.parse_args(argv)
    path = write_sbom(args.dependency_lock, args.output, target=args.target)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
