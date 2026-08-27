#!/usr/bin/env python3
"""Validate release coordinates and an allowlisted package payload."""

from __future__ import annotations

import argparse
import email.message
import email.parser
import io
import json
import re
import tarfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath


FORBIDDEN_PARTS = {
    ".env",
    ".git",
    ".github",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
}
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pem", ".key", ".pyc"}


def fail(message: str) -> None:
    raise SystemExit(message)


def safe_names(names: list[str]) -> None:
    for raw_name in names:
        name = PurePosixPath(raw_name)
        if name.is_absolute() or ".." in name.parts:
            fail(f"unsafe package path: {raw_name}")
        if FORBIDDEN_PARTS.intersection(name.parts) or name.suffix in FORBIDDEN_SUFFIXES:
            fail(f"forbidden package content: {raw_name}")


def validate_python(path: Path, version: str) -> None:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            safe_names(names)
            metadata_name = next((name for name in names if name.endswith(".dist-info/METADATA")), None)
            if metadata_name is None:
                fail("wheel is missing METADATA")
            metadata = email.parser.Parser().parsestr(archive.read(metadata_name).decode())
            check_python_metadata(metadata, version)
            required = ["robotscenter/__init__.py", "robotscenter/py.typed"]
            if not all(item in names for item in required):
                fail("wheel is missing import package or py.typed marker")
            if not any(name.endswith(".dist-info/licenses/LICENSE") for name in names):
                fail("wheel is missing LICENSE")
            if not any(name.endswith(".dist-info/licenses/NOTICE") for name in names):
                fail("wheel is missing NOTICE")
        return

    if path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            names = archive.getnames()
            safe_names(names)
            metadata_name = next((name for name in names if name.endswith("/PKG-INFO")), None)
            if metadata_name is None:
                fail("sdist is missing PKG-INFO")
            metadata_file = archive.extractfile(metadata_name)
            if metadata_file is None:
                fail("could not read sdist PKG-INFO")
            check_python_metadata(email.parser.Parser().parsestr(metadata_file.read().decode()), version)
            required_suffixes = ["/LICENSE", "/NOTICE", "/README.md", "/pyproject.toml"]
            if not all(any(name.endswith(suffix) for name in names) for suffix in required_suffixes):
                fail("sdist is missing required license, notice, readme, or build metadata")
        return

    fail("Python artifact must be a wheel or sdist")


def check_python_metadata(metadata: email.message.Message, version: str) -> None:
    if metadata["Name"] != "robotscenter" or metadata["Version"] != version:
        fail(f"unexpected Python coordinate: {metadata['Name']} {metadata['Version']}")


def validate_typescript(path: Path, version: str) -> None:
    with tarfile.open(path, "r:gz") as archive:
        names = archive.getnames()
        safe_names(names)
        package = json.load(archive.extractfile("package/package.json"))  # type: ignore[arg-type]
        if package.get("name") != "@robotscenter/sdk" or package.get("version") != version:
            fail(f"unexpected npm coordinate: {package.get('name')} {package.get('version')}")
        required = {
            "package/LICENSE",
            "package/NOTICE",
            "package/README.md",
            "package/dist/index.js",
            "package/dist/index.cjs",
            "package/dist/index.d.ts",
        }
        missing = required.difference(names)
        if missing:
            fail(f"npm package is missing: {sorted(missing)}")


def validate_elixir(path: Path, version: str) -> None:
    with tarfile.open(path) as archive:
        outer_names = archive.getnames()
        safe_names(outer_names)
        metadata_file = archive.extractfile("metadata.config")
        contents_file = archive.extractfile("contents.tar.gz")
        if metadata_file is None or contents_file is None:
            fail("Hex archive is missing metadata or contents")
        metadata = metadata_file.read().decode()
        if not re.search(r'\{<<"name">>,<<"robots_center">>\}', metadata):
            fail("Hex archive has the wrong package name")
        if not re.search(rf'\{{<<"version">>,<<"{re.escape(version)}">>\}}', metadata):
            fail("Hex archive has the wrong version")
        with tarfile.open(fileobj=io.BytesIO(contents_file.read()), mode="r:gz") as contents:
            names = contents.getnames()
            safe_names(names)
            required = {"LICENSE", "NOTICE", "README.md", "mix.exs", "lib/robots_center.ex"}
            missing = required.difference(names)
            if missing:
                fail(f"Hex package is missing: {sorted(missing)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("package", choices=["python", "typescript", "elixir"])
    parser.add_argument("artifact", type=Path)
    parser.add_argument("version", nargs="?")
    args = parser.parse_args()
    if not args.artifact.is_file():
        fail(f"artifact not found: {args.artifact}")
    version = args.version or source_version(args.package)
    validators = {
        "python": validate_python,
        "typescript": validate_typescript,
        "elixir": validate_elixir,
    }
    validators[args.package](args.artifact, version)


def source_version(package: str) -> str:
    if package == "python":
        return str(tomllib.loads(Path("packages/python/pyproject.toml").read_text())["project"]["version"])
    if package == "typescript":
        return str(json.loads(Path("packages/typescript/package.json").read_text())["version"])
    match = re.search(r'version:\s*"([^"]+)"', Path("packages/elixir/mix.exs").read_text())
    if match is None:
        fail("could not read the Elixir package version")
    return match.group(1)


if __name__ == "__main__":
    main()
