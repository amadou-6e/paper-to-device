"""Tests for async operation contracts used by desktop UI."""

import unittest
from pathlib import Path

from ui_contracts import UiOperationContracts


class UiOperationContractsTests(unittest.TestCase):
    def test_preview_stale_completion_is_ignored(self):
        contracts = UiOperationContracts()
        file_a = Path("a.pdf")
        file_b = Path("b.pdf")

        token_a = contracts.start_preview(file_a)
        token_b = contracts.start_preview(file_b)

        self.assertFalse(contracts.complete_preview(token_a))
        self.assertTrue(contracts.has_active_preview)
        self.assertTrue(contracts.is_preview_active_for(file_b))
        self.assertTrue(contracts.complete_preview(token_b))
        self.assertFalse(contracts.has_active_preview)

    def test_export_stale_completion_is_ignored(self):
        contracts = UiOperationContracts()

        token_a = contracts.start_export()
        token_b = contracts.start_export()

        self.assertFalse(contracts.complete_export(token_a))
        self.assertTrue(contracts.has_active_export)
        self.assertTrue(contracts.complete_export(token_b))
        self.assertFalse(contracts.has_active_export)


if __name__ == "__main__":
    unittest.main()
