from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import stage_signed_deploy  # noqa: E402


class StageSignedDeployTests(unittest.TestCase):
    def test_signature_is_staged_beside_package_for_fixed_helper_root(self):
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            package = root / "candidate.zip"
            signature = root / "Re-Gear-update-0.3.122-aaaaaaaaaaaa.zip.sig"
            package.write_bytes(b"package")
            signature.write_bytes(b"signature")

            completed = type("Completed", (), {"returncode": 0, "stderr": ""})()
            with (
                patch.object(
                    stage_signed_deploy,
                    "inspect_package",
                    return_value={"version": "0.3.122", "revision": "a" * 40},
                ),
                patch.object(
                    stage_signed_deploy,
                    "stage_package",
                    return_value={"state": "staged", "filename": signature.name[:-4]},
                ),
                patch.object(stage_signed_deploy.subprocess, "run", return_value=completed) as run,
            ):
                result = stage_signed_deploy.stage_signed_package(
                    package=package, signature=signature, host="192.0.2.146"
                )

        self.assertEqual(result["signature"], signature.name)
        argv = run.call_args.args[0]
        self.assertEqual(argv[-1], f"deck@192.0.2.146:{signature.name}")
        self.assertNotIn("Downloads", argv[-1])


if __name__ == "__main__":
    unittest.main()
