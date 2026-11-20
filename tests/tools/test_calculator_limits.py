"""Huge powers must fail fast instead of freezing the PC."""

from __future__ import annotations

import time

import pytest

from openjarvis.tools.calculator import _safe_eval_node


def _eval(expr):
    import ast

    return _safe_eval_node(ast.parse(expr, mode="eval").body)


@pytest.mark.parametrize("expr", ["9**9**9", "10**100000", "2**(10**6)"])
def test_huge_powers_are_refused(expr):
    start = time.monotonic()
    with pytest.raises(ValueError):
        _eval(expr)
    assert time.monotonic() - start < 1


def test_normal_powers_work():
    assert _eval("2**10") == 1024
    assert _eval("1.05**12") == pytest.approx(1.7958563)
