"""Where `mercapi` is allowed to appear.

The whole point of the adapter is that a change in the fork or in Mercari's
response shape stops at one module. An import of `mercapi` from the domain or
the application layer removes that guarantee quietly: everything still runs, and
the boundary is gone.

Read statically, so an import inside a function is caught too.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


PACKAGE = Path(__file__).resolve().parents[2] / "card_digger"
CONTAINED_LAYERS = ("domain", "application")


def modules_of(layer: str) -> list[Path]:
    return sorted((PACKAGE / layer).rglob("*.py"))


def imported_names(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def borrowed_private_attributes(source: str) -> set[str]:
    """Private attributes read off some object other than our own.

    `self._client` is this package's own state. `client._client` reaches into
    somebody else's, which for a fork object means depending on something the
    fork never promised to keep.
    """
    return {
        node.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute)
        and node.attr.startswith("_")
        and not node.attr.startswith("__")
        and not (isinstance(node.value, ast.Name) and node.value.id in {"self", "cls"})
    }


@pytest.mark.parametrize("layer", CONTAINED_LAYERS)
def test_the_layer_has_modules_to_check(layer):
    assert modules_of(layer), f"no module found under {layer}"


@pytest.mark.parametrize("layer", CONTAINED_LAYERS)
def test_the_marketplace_library_stays_behind_the_adapter(layer):
    offenders = {
        module.name
        for module in modules_of(layer)
        if any(
            name == "mercapi" or name.startswith("mercapi.")
            for name in imported_names(module.read_text(encoding="utf-8"))
        )
    }

    assert offenders == set()


@pytest.mark.parametrize("layer", CONTAINED_LAYERS)
def test_the_layer_does_not_reach_into_an_adapter(layer):
    offenders = {
        module.name
        for module in modules_of(layer)
        if any(
            name.startswith("card_digger.adapters")
            for name in imported_names(module.read_text(encoding="utf-8"))
        )
    }

    assert offenders == set()


def test_the_domain_does_not_depend_on_the_application():
    offenders = {
        module.name
        for module in modules_of("domain")
        if any(
            name.startswith("card_digger.application")
            for name in imported_names(module.read_text(encoding="utf-8"))
        )
    }

    assert offenders == set()


def test_no_private_member_of_the_fork_is_used():
    """The fork's public API is the contract. A `_` attribute is not part of it.

    Checked on the adapter package, which is the only place that holds a fork
    object at all.
    """
    offenders = {
        module.name: borrowed
        for module in sorted((PACKAGE / "adapters").rglob("*.py"))
        if (borrowed := borrowed_private_attributes(module.read_text(encoding="utf-8")))
    }

    assert offenders == {}, f"private members reached for: {offenders}"
