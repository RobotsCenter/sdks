#!/usr/bin/env python3
"""Verify downloaded release evidence before a registry publication."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    args = parser.parse_args()
    evidence = json.loads((args.artifact_dir / "release-provenance.json").read_text())
    assert evidence["package"] == args.package
    assert evidence["tag"] == args.tag
    assert evidence["commit"] == args.commit
    expected_paths = set()
    for artifact in evidence["artifacts"]:
        path = args.artifact_dir / artifact["path"]
        assert path.is_file(), f"missing release artifact: {path}"
        assert path.stat().st_size == artifact["bytes"], f"size differs: {path}"
        assert sha256(path) == artifact["sha256"], f"SHA-256 differs: {path}"
        expected_paths.add(path.resolve())
    actual_paths = {
        path.resolve()
        for path in (args.artifact_dir / "distributions").rglob("*")
        if path.is_file()
    }
    assert actual_paths == expected_paths, "distribution set differs from release evidence"
    print("release evidence verified")


if __name__ == "__main__":
    main()
