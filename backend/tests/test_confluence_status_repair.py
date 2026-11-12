"""Guard checks for the local draft-only repair utility."""
from types import SimpleNamespace
import unittest
from app.services.confluence_status_repair import choose_editable_draft


class RepairGuardTests(unittest.TestCase):
    def test_no_open_draft_refused(self):
        with self.assertRaises(ValueError):
            choose_editable_draft([])

    def test_multiple_open_revisions_refused(self):
        with self.assertRaises(ValueError):
            choose_editable_draft([SimpleNamespace(state='draft'), SimpleNamespace(state='draft')])

    def test_only_draft_accepted(self):
        for state in ('published', 'in_review', 'approved', 'superseded', 'retired'):
            with self.assertRaises(ValueError):
                choose_editable_draft([SimpleNamespace(state=state)])
        draft = SimpleNamespace(state='draft')
        self.assertIs(choose_editable_draft([draft]), draft)
