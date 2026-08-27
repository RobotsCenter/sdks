#!/usr/bin/env python3
"""Compare committed SDK contracts with an explicitly selected deployment."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path


SURFACES = {
    "openapi.json": "/api/v1/openapi/agent-communication.json",
    "realtime.json": "/api/v1/realtime/agent-communication.json",
}


def load_url(url: str) -> object:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "robotscenter-release-gate"})
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise SystemExit(f"contract endpoint returned HTTP {response.status}: {url}")
        return json.load(response)


def normalize_contract(value: object, *, key: str | None = None) -> object:
    """Normalize OAS set-like required arrays without reordering semantic arrays."""
    if isinstance(value, dict):
        return {
            child_key: normalize_contract(child, key=child_key)
            for child_key, child in sorted(value.items())
        }
    if isinstance(value, list):
        normalized = [normalize_contract(child) for child in value]
        if key == "required" and all(isinstance(child, str) for child in normalized):
            return sorted(set(normalized))
        return normalized
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    source = json.loads((Path("contracts") / "source.json").read_text())
    for filename, path in SURFACES.items():
        committed = json.loads((Path("contracts") / filename).read_text())
        digest = hashlib.sha256((Path("contracts") / filename).read_bytes()).hexdigest()
        if source["surfaces"][filename]["sha256"] != digest:
            raise SystemExit(f"{filename} does not match contracts/source.json")
        if source["surfaces"][filename]["endpoint"] != path:
            raise SystemExit(f"{filename} endpoint does not match contracts/source.json")
        deployed = load_url(base_url + path)
        if normalize_contract(deployed) != normalize_contract(committed):
            raise SystemExit(f"{filename} differs from {base_url + path}; refresh and review the snapshot before release")
        print(f"verified {filename} against {base_url + path}")


if __name__ == "__main__":
    main()
