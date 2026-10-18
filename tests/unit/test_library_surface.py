"""Every name the integration imports from the blaueis library is declared in
that module's ``__all__``, so a library release that drops or renames one
fails here instead of at import time on a user's Home Assistant."""

import ast
import importlib
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[2] / "custom_components" / "blaueis_midea"


def _imports() -> list[tuple[str, str, str]]:
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("blaueis."):
                found.extend((path.name, node.module, alias.name) for alias in node.names)
    return found


@pytest.mark.parametrize(("source", "module", "name"), _imports())
def test_imported_name_is_public(source, module, name):
    mod = importlib.import_module(module)
    assert name in getattr(mod, "__all__", ()), f"{source} imports {module}.{name}, which is not in __all__"
