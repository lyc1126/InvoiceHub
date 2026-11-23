#!/usr/bin/env python3
"""Build the preview-only sidecar from SHA-locked jars and a native Java 21 JDK."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools/ofd-preview"
MODULES = "java.base,java.desktop,java.xml,java.logging,java.naming,java.management,java.sql,jdk.unsupported,jdk.charsets,jdk.crypto.ec"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def platform_id() -> str:
    if os.name == "nt" and platform.machine().lower() in {"amd64", "x86_64"}:
        return "windows-x64"
    if platform.system() == "Darwin" and platform.machine().lower() in {"arm64", "aarch64"}:
        return "macos-arm64"
    raise ValueError("build on Windows x64 or macOS arm64")


def fetch(entry: dict, destination: Path) -> None:
    if destination.is_file() and sha(destination) == entry["sha256"]:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    try:
        with urllib.request.urlopen(entry["url"], timeout=30) as response, partial.open("wb") as output:
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > entry["size"]:
                    raise ValueError("download exceeds locked size")
                output.write(chunk)
        if size != entry["size"] or sha(partial) != entry["sha256"]:
            raise ValueError(f"download integrity mismatch: {destination.name}")
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)


def build(jdk_archive: Path, dependencies: Path, output: Path) -> dict:
    target = platform_id()
    toolchain = json.loads((SOURCE / "toolchains.lock.json").read_text())[target]
    lock = json.loads((SOURCE / "dependencies.lock.json").read_text())
    if output.exists():
        raise ValueError("output already exists; use a new component directory")
    if sha(jdk_archive) != toolchain["sha256"]:
        raise ValueError("JDK archive SHA256 does not match toolchains.lock.json")
    for entry in lock:
        if sha(dependencies / entry["filename"]) != entry["sha256"]:
            raise ValueError(f"dependency SHA256 mismatch: {entry['filename']}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="invoicehub-ofd-build-") as temp_name:
        temp = Path(temp_name)
        if target == "macos-arm64":
            with tarfile.open(jdk_archive) as archive:
                archive.extractall(temp / "jdk", filter="data")
        else:
            with zipfile.ZipFile(jdk_archive) as archive:
                archive.extractall(temp / "jdk")  # Exact SHA-pinned vendor archive, never user OFD.
        jdk = temp / "jdk" / toolchain["jdk_home"]
        exe = ".exe" if os.name == "nt" else ""
        staged = temp / "component"
        lib = staged / "lib"
        lib.mkdir(parents=True)
        for entry in lock:
            shutil.copyfile(dependencies / entry["filename"], lib / entry["filename"])
        classes = temp / "classes"
        classes.mkdir()
        env = {k: v for k, v in os.environ.items() if k not in {
            "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS", "CLASSPATH"}}
        def run(args: list[str]) -> None:
            subprocess.run(args, check=True, env=env, timeout=180)
        run([str(jdk / "bin" / f"javac{exe}"), "-encoding", "UTF-8", "--release", "21",
             "-cp", os.pathsep.join(str(p) for p in sorted(lib.glob("*.jar"))),
             "-d", str(classes), *[str(p) for p in sorted((SOURCE / "src/main/java").rglob("*.java"))]])
        run([str(jdk / "bin" / f"jar{exe}"), "--create", "--file", str(lib / "ofd-preview.jar"),
             "--date=2026-09-08T00:00:00Z", "-C", str(classes), "."])
        run([str(jdk / "bin" / f"jlink{exe}"), "--add-modules", MODULES, "--strip-debug",
             "--no-header-files", "--no-man-pages", "--compress=zip-6", "--output", str(staged / "java")])
        # Keep vendor/third-party notices and dependency identities inside the component;
        # the enclosing Python runtime manifest must hash this entire tree after install.
        shutil.copyfile(SOURCE / "dependencies.lock.json", staged / "dependencies.lock.json")
        shutil.copyfile(SOURCE / "toolchains.lock.json", staged / "toolchains.lock.json")
        shutil.copyfile(SOURCE / "NOTICE.md", staged / "NOTICE.md")
        shutil.copyfile(ROOT / "LICENSE", staged / "LICENSE")
        shutil.copyfile(SOURCE / "LICENSE-OFDRW", staged / "LICENSE-OFDRW")
        source_files = [SOURCE / "pom.xml", SOURCE / "NOTICE.md", SOURCE / "dependencies.lock.json", SOURCE / "toolchains.lock.json",
                        SOURCE / "LICENSE-OFDRW", ROOT / "LICENSE",
                        *sorted((SOURCE / "src/main/java").rglob("*.java")), Path(__file__)]
        source_hashes = {p.relative_to(ROOT).as_posix(): sha(p) for p in source_files}
        fingerprint = hashlib.sha256(json.dumps(source_hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        sbom = {"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1, "components": [
            {"type": "library", "group": e["group"], "name": e["name"], "version": e["version"],
             "purl": f"pkg:maven/{e['group']}/{e['name']}@{e['version']}",
             "hashes": [{"alg": "SHA-256", "content": e["sha256"]}]} for e in lock]}
        sbom["components"].append({"type": "application", "name": "Azul Zulu OpenJDK",
                                   "version": toolchain["java_version"],
                                   "hashes": [{"alg": "SHA-256", "content": toolchain["sha256"]}]})
        (staged / "sbom.cdx.json").write_text(json.dumps(sbom, indent=2) + "\n", encoding="utf-8")
        files = {p.relative_to(staged).as_posix(): sha(p) for p in sorted(staged.rglob("*")) if p.is_file()}
        manifest = {"schema_version": 1, "engine": "ofdrw-2.4.0", "platform": target,
                    "java_major": 21, "java_version": toolchain["java_version"],
                    "jdk_archive_sha256": toolchain["sha256"], "modules": MODULES.split(","),
                    "source_files": source_hashes, "source_fingerprint": fingerprint, "files": files,
                    "total_bytes": sum(p.stat().st_size for p in staged.rglob("*") if p.is_file())}
        (staged / "component.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        shutil.copytree(staged, output, symlinks=False)
        return {k: manifest[k] for k in ("platform", "engine", "java_version", "total_bytes")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jdk-archive", type=Path)
    parser.add_argument("--dependencies", type=Path)
    parser.add_argument("--fetch", action="store_true", help="download only the SHA-locked build inputs")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "runtime/ofd-build-cache")
    parser.add_argument("--output", type=Path, default=ROOT / "runtime/components/ofd-preview")
    args = parser.parse_args()
    if args.fetch:
        if args.jdk_archive or args.dependencies:
            parser.error("--fetch cannot be combined with explicit archive/dependency paths")
        toolchain = json.loads((SOURCE / "toolchains.lock.json").read_text())[platform_id()]
        args.jdk_archive = args.cache_dir / Path(toolchain["url"]).name
        args.dependencies = args.cache_dir / "lib"
        fetch(toolchain, args.jdk_archive)
        for entry in json.loads((SOURCE / "dependencies.lock.json").read_text()):
            fetch(entry, args.dependencies / entry["filename"])
    elif not args.jdk_archive or not args.dependencies:
        parser.error("provide --fetch or both --jdk-archive and --dependencies")
    print(json.dumps(build(args.jdk_archive.resolve(), args.dependencies.resolve(), args.output.resolve())))


if __name__ == "__main__":
    main()
