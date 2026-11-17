"""Safety tests for legacy autonomous transaction paths."""

import unittest
from unittest.mock import patch

from src.core import auto_swap


class AutoSwapSafetyTests(unittest.TestCase):
    def test_auto_swap_is_blocked_even_when_force_is_true(self):
        with patch.object(auto_swap.settings, "AUTONOMOUS_TRANSACTIONS_ENABLED", False):
            with patch.object(auto_swap, "_get_wallet") as get_wallet:
                result = auto_swap.do_auto_swap(
                    wallet_label="farm-01",
                    chain="polygon",
                    force=True,
                )

        self.assertIsNone(result)
        get_wallet.assert_not_called()


if __name__ == "__main__":
    unittest.main()
