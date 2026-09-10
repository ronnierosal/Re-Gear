from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from regear.domain.game_save import (  # noqa: E402
    GameSaveProofObservation,
    GameSaveProofState,
    VerifiedGameSaveRecipe,
)


class GameSaveDomainTests(unittest.TestCase):
    def test_recipe_requires_exact_app_and_categorical_evidence(self):
        with self.assertRaisesRegex(ValueError, "AppID"):
            VerifiedGameSaveRecipe(
                "recipe-1", "evidence-1", "0", "host", "egpu"
            )
        with self.assertRaisesRegex(ValueError, "identity"):
            VerifiedGameSaveRecipe(
                "../../recipe", "evidence-1", "1234", "host", "egpu"
            )

    def test_unknown_proof_is_never_exact(self):
        unknown = GameSaveProofObservation(
            GameSaveProofState.UNKNOWN, "generation-1", "sample-1"
        )
        verified = GameSaveProofObservation(
            GameSaveProofState.VERIFIED, "generation-2", "sample-2"
        )
        self.assertFalse(unknown.exact)
        self.assertTrue(verified.exact)


if __name__ == "__main__":
    unittest.main()
