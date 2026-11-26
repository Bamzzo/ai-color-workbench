"""DocumentSession unit tests."""

from __future__ import annotations

import unittest

from app.session import DocumentSession
from baker.params import ColorParams


class SessionTests(unittest.TestCase):
    def test_undo_redo_params(self) -> None:
        session = DocumentSession()
        session.reset_color_history()
        session.state.params = ColorParams.identity().with_updates(contrast=5)
        session.state.bump_color()
        session.record_color_history()
        session.state.params = ColorParams.identity().with_updates(contrast=15)
        session.state.bump_color()
        session.record_color_history()
        self.assertTrue(session.can_undo())
        self.assertFalse(session.can_redo())
        session.undo()
        self.assertAlmostEqual(session.state.params.contrast, 5.0)
        self.assertTrue(session.can_redo())
        session.redo()
        self.assertAlmostEqual(session.state.params.contrast, 15.0)

    def test_export_gate(self) -> None:
        session = DocumentSession()
        token = session.export_started("图片", 1, "a.png")
        self.assertGreater(token, 0)
        self.assertEqual(session.outstanding_exports(0), 1)
        reason = session.export_block_reason(0)
        self.assertIn("导出", reason or "")
        session.export_take(token, "图片")
        self.assertIsNone(session.export_block_reason(0))


if __name__ == "__main__":
    unittest.main()