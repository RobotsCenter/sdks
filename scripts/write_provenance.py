#!/usr/bin/env python3
"""Write a deterministic release evidence file with artifact and contract hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    args = parser.parse_args()
    evidence_name = "release-provenance.json"
    files = sorted(path for path in args.artifact_dir.rglob("*") if path.is_file() and path.name != evidence_name)
    evidence = {
        "schema_version": 1,
        "package": args.package,
        "tag": args.tag,
        "commit": args.commit,
        "repository": os.environ.get("GITHUB_REPOSITORY"),
        "workflow_run": os.environ.get("GITHUB_RUN_ID"),
        "artifacts": [
            {
                "path": path.relative_to(args.artifact_dir).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in files
        ],
        "contracts": {
            name: sha256(Path("contracts") / name)
            for name in ("openapi.json", "realtime.json", "source.json")
        },
    }
    (args.artifact_dir / evidence_name).write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
