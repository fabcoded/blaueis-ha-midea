"""Fail when requirements-dev.txt and manifest.json pin different blaueis versions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _blaueis_pins(lines: list[str]) -> dict[str, str]:
    pins = {}
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if line.startswith("blaueis-"):
            name, _, version = line.partition("==")
            pins[name] = version
    return pins


def main() -> int:
    manifest = json.loads((ROOT / "custom_components" / "blaueis_midea" / "manifest.json").read_text())
    from_manifest = _blaueis_pins(manifest["requirements"])
    from_dev = _blaueis_pins((ROOT / "requirements-dev.txt").read_text().splitlines())
    if not from_manifest or from_manifest != from_dev:
        print(f"pin mismatch: manifest.json {from_manifest} != requirements-dev.txt {from_dev}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
