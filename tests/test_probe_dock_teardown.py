"""Pin the probe call site against the decision signature it calls.

`scripts/probe_dock_teardown.py` is the only runtime caller of
`decide_dock_teardown`. It drifted and nobody noticed: commit `d05f091`
renamed the parameter `approved` to `approval` and updated the domain and the
domain's own tests, but not this call site. The probe raised

    TypeError: decide_dock_teardown() got an unexpected keyword argument 'approved'

on every run from then on. Nothing imported the probe and nothing tested it,
so the suite stayed green while the one thing that actually ran was broken.

These tests read the real call out of the real source and bind it against the
real signature, so the next rename of either side fails here instead of on an
operator's device. They deliberately do not execute `main()`: it reads sysfs,
and the failure being guarded is argument drift, which is visible statically.
"""

from __future__ import annotations

import ast
import inspect
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.adapters.steamos.dock_branch import TunnelReading  # noqa: E402
from regear.domain.dock_teardown import decide_dock_teardown  # noqa: E402


PROBE = ROOT / "scripts" / "probe_dock_teardown.py"


def _decide_call() -> ast.Call:
    """The single `decide_dock_teardown(...)` call in the probe."""
    tree = ast.parse(PROBE.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "decide_dock_teardown"
    ]
    assert len(calls) == 1, f"expected exactly one call, found {len(calls)}"
    return calls[0]


class ProbeCallSiteTests(unittest.TestCase):
    def test_the_probe_arguments_bind_to_the_decision_signature(self):
        """The exact failure that shipped: a keyword the function does not take."""
        call = _decide_call()
        self.assertEqual(call.args, [], "the decision is keyword-only")
        keywords = [keyword.arg for keyword in call.keywords]
        self.assertNotIn(None, keywords, "no ** unpacking; names must be checkable")

        signature = inspect.signature(decide_dock_teardown)
        # Values are irrelevant here; only the names have to be bindable.
        signature.bind_partial(**{name: None for name in keywords})

    def test_the_probe_supplies_every_required_argument(self):
        """bind_partial above accepts a call that is merely not wrong yet."""
        call = _decide_call()
        keywords = {keyword.arg for keyword in call.keywords}
        required = {
            name
            for name, parameter in inspect.signature(decide_dock_teardown).parameters.items()
            if parameter.default is inspect.Parameter.empty
        }
        self.assertEqual(required - keywords, set())

    def test_a_probe_never_carries_an_approval(self):
        """Intent, not just type-compatibility.

        A probe reports the substantive blocker; producing a permitted
        decision is not its job. Passing a real approval here would let a
        read-only diagnostic reach `permitted`.
        """
        call = _decide_call()
        approval = [
            keyword.value for keyword in call.keywords if keyword.arg == "approval"
        ]
        self.assertEqual(len(approval), 1, "the probe states its approval explicitly")
        self.assertIsInstance(approval[0], ast.Constant)
        self.assertIsNone(approval[0].value)


class ProbeReportTests(unittest.TestCase):
    """What the adapter observes, the probe has to say out loud.

    The probe exists to report the substantive blocker. A reading the
    adapter produces and the probe drops is a blocker an operator never
    sees -- and when the dropped field is the reason for a refusal, they
    are told the scan failed instead of what actually happened.
    """

    def test_every_tunnel_reading_field_is_reported(self):
        source = PROBE.read_text(encoding="utf-8")
        reported = {
            node.attr
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "tunnel"
        }
        missing = set(TunnelReading.__dataclass_fields__) - reported
        self.assertEqual(
            missing,
            set(),
            f"observed by the adapter but never reported: {sorted(missing)}",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
