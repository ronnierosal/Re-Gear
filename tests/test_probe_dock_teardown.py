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


sys.path.insert(0, str(ROOT / "scripts"))
import probe_dock_teardown as probe  # noqa: E402

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


class ProbeIdentityTests(unittest.TestCase):
    """The probe has to be able to describe a dock it was not written for.

    Its own docstring says #147 is undecided and this produces the evidence
    that decision needs. Evidence from one hardware pairing cannot answer a
    question about docks in general, and a captured report that does not name
    its own hardware cannot be compared with one from another dock.
    """

    def test_the_defaults_still_describe_the_tested_pairing(self):
        """Existing operator instructions must keep working unchanged."""
        options = probe.parser().parse_args([])

        self.assertEqual(options.usb_controller, "0000:09:00.0")
        self.assertEqual(options.tunnel_name, "Tapex Creek")
        self.assertEqual(
            tuple(options.gpu_function or probe.DEFAULT_GPU_FUNCTIONS),
            ("0000:08:00.0", "0000:08:00.1"),
        )

    def test_another_dock_can_be_described(self):
        options = probe.parser().parse_args(
            [
                "--usb-controller", "0000:aa:00.0",
                "--tunnel-name", "Some Other Dock",
                "--gpu-function", "0000:bb:00.0",
                "--gpu-function", "0000:bb:00.1",
            ]
        )

        self.assertEqual(options.usb_controller, "0000:aa:00.0")
        self.assertEqual(options.tunnel_name, "Some Other Dock")
        self.assertEqual(
            tuple(options.gpu_function), ("0000:bb:00.0", "0000:bb:00.1")
        )

    def test_the_parsed_identity_is_the_one_actually_observed(self):
        """Parsing an argument and then ignoring it looks identical from outside.

        Checking `parser()` alone proves only that the flags exist. A `main`
        that accepted `--usb-controller` and then observed the hardcoded
        default would satisfy every other test here while quietly reporting
        the wrong dock -- and the report would name the requested one.
        """
        observed = {}
        for node in ast.walk(ast.parse(PROBE.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if name not in {
                "observe_usb",
                "observe_storage",
                "observe_tunnel",
                "attached_gpu_functions",
            }:
                continue
            self.assertEqual(len(node.args), 1, f"{name} takes one identity")
            observed[name] = node.args[0]

        for name in (
            "observe_usb",
            "observe_storage",
            "observe_tunnel",
            "attached_gpu_functions",
        ):
            self.assertIn(name, observed, f"{name} is never called")

        for name in ("observe_usb", "observe_storage", "observe_tunnel"):
            argument = observed[name]
            self.assertIsInstance(
                argument, ast.Attribute, f"{name} must observe a parsed option"
            )
            self.assertEqual(
                getattr(argument.value, "id", None),
                "options",
                f"{name} must observe a parsed option, not a module constant",
            )

        # The GPU functions are derived once, so this one binds to that local.
        self.assertIsInstance(observed["attached_gpu_functions"], ast.Name)
        self.assertEqual(observed["attached_gpu_functions"].id, "gpu_functions")

    def test_the_report_records_which_dock_it_describes(self):
        """A reading whose subject is a command-line choice must say so."""
        keys = {
            node.value
            for node in ast.walk(ast.parse(PROBE.read_text(encoding="utf-8")))
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        for required in (
            "identity",
            "gpu_functions",
            "usb_controller",
            "tunnel_name",
        ):
            self.assertIn(required, keys)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
