#!/usr/bin/env python3
"""Read the addon version and fail if the three version fields disagree."""

from __future__ import annotations

import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    manifest = (ROOT / "polyassetvault" / "blender_manifest.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version = "([0-9]+\.[0-9]+\.[0-9]+)"\s*$', manifest)
    if not match:
        fail("Could not read version from blender_manifest.toml")
    version = match.group(1)
    if not SEMVER.fullmatch(version):
        fail(f"Invalid version {version!r}")

    init = (ROOT / "polyassetvault" / "__init__.py").read_text(encoding="utf-8")
    init_match = re.search(r'"version":\s*\((\d+),\s*(\d+),\s*(\d+)\)', init)
    if not init_match:
        fail("Could not read bl_info version from __init__.py")
    init_version = ".".join(init_match.groups())
    if init_version != version:
        fail(f"__init__.py version {init_version} does not match {version}")

    api = (ROOT / "polyassetvault" / "api.py").read_text(encoding="utf-8")
    api_match = re.search(r'^ADDON_VERSION = "([0-9]+\.[0-9]+\.[0-9]+)"\s*$', api, re.M)
    if not api_match or api_match.group(1) != version:
        fail(f"ADDON_VERSION does not match {version}")

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"version={version}\n")
    print(version)


if __name__ == "__main__":
    main()
