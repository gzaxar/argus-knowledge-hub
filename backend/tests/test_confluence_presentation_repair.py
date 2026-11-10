"""Isolated execution of the actual repair function with in-memory collaborators.
These tests do not exercise SQLAlchemy or a live database.
"""
import ast, sys, uuid, unittest, io, re
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace as N
from unittest.mock import MagicMock
from urllib.parse import urlparse
from contextlib import redirect_stdout
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from app.services.confluence_file_macros import FILE_VIEWER_MACROS, render_file_macro, replace_file_viewer_placeholders
from app.services.confluence_presentation import prepare_presentation
pattern = re.compile('<ac:structured-macro[^>]*ac:name="([^"]+)"(?:(?!<ac:structured-macro).)*?</ac:structured-macro>', re.S)
macro = '<ac:structured-macro ac:name="view-file"><ac:parameter ac:name="name"><ri:attachment ri:filename="cx2000_en.pdf" /></ac:parameter></ac:structured-macro>'
marker = '*[view-file — see the original page]*'
link = '[cx2000_en.pdf](/v1/attachments/file)'
body = 'Published intro\n' + marker + '\nManual'
tree = ast.parse((root / 'app/services/confluence_file_repair.py').read_text())
tree.body = [n for n in tree.body if getattr(n, 'name', None) == 'repair']

class DraftRepairChecks(unittest.TestCase):

    def setup_case(self, apply=False, state='draft', use=False, open_exists=True, changed=False, version=8, already_fixed=False, presentation=False, summary=''):
        doc = N(uid='doc', code='CONF-117374977', title='Modulator', current_revision_uid='published')
        current = N(uid='published', state='published', body_markdown=body, attributes={'argus_source_id': '117374977', 'argus_source_version': 8, 'argus_source_url': 'https://site.atlassian.net/wiki/pages/viewpage.action?pageId=117374977'}, steps=['preserve'], valid_from=None, valid_until=None, next_review_due=None)
        draft = N(uid='draft', state=state, body_markdown='My saved edits\n' + (link if already_fixed else marker) + '\nManual', attributes={'local': 'keep', **({'argus_summary': summary} if summary else {})}, steps=['edited'])
        locked = deepcopy(draft)
        if changed:
            locked.body_markdown += 'Someone edited this'
        config = N(params={'base_url': 'https://site.atlassian.net/wiki', 'auth_mode': 'cloud_basic', 'email': 'u@example.org'}, encrypted_secret='cipher', name='test')
        db = MagicMock()
        db.execute.return_value.all.return_value = [(doc, current)]
        db.scalars.side_effect = [N(all=lambda: [draft] if open_exists else []), N(all=lambda: [config])] + ([] if presentation else [N(all=lambda: [N(filename='cx2000_en.pdf', uid='file')])]) + [N(all=lambda: [locked] if open_exists else [])]
        db.scalar.side_effect = [doc, 1]
        db.get.return_value = current
        model = MagicMock()
        model.side_effect = lambda **kw: N(**kw)
        page = {'id': '117374977', 'title': 'Exact Confluence title', 'version': {'number': version}, 'body': {'storage': {'value': '<p>This source introduction describes the modulator Ethernet connection.</p>' + macro}}}
        env = dict(prepare_presentation=prepare_presentation, SessionLocal=lambda: db, select=lambda *a: MagicMock(), func=MagicMock(), Document=MagicMock(), DocumentRevision=model, ImportConfig=MagicMock(), Attachment=MagicMock(), parse_page_link=lambda x: {'base_url': 'https://site.atlassian.net/wiki'}, urlparse=urlparse, decrypt_secret=lambda x: 'not-printed', _TimeoutSession=lambda: N(get=lambda *a, **kw: page, close=lambda: None), configure_confluence_session=lambda s, b, *a: b, resolve_api_base=lambda s, b: b, confluence_json=lambda r: r, _INNERMOST_MACRO=pattern, FILE_VIEWER_MACROS=FILE_VIEWER_MACROS, render_file_macro=render_file_macro, storage_to_markdown=lambda *a: link, replace_file_viewer_placeholders=replace_file_viewer_placeholders, deepcopy=deepcopy, uuid=uuid)
        exec(compile(tree, 'repair', 'exec'), env)
        self.db = db
        self.current = current
        self.doc = doc
        self.draft = draft
        self.locked = locked
        return lambda: env['repair']('eli', '117374977', apply=apply, use_existing_draft=use, presentation_only=presentation)

class PresentationRepairChecks(unittest.TestCase):
    setup_case = DraftRepairChecks.setup_case

    def test_presentation_preview_does_not_write(self):
        run = self.setup_case(use=True, presentation=True, already_fixed=True)
        with redirect_stdout(io.StringIO()):
            run()
        self.db.commit.assert_not_called()
        self.db.add.assert_not_called()

    def test_presentation_apply_preserves_pdf_link_and_adds_summary(self):
        run = self.setup_case(use=True, apply=True, presentation=True, already_fixed=True)
        with redirect_stdout(io.StringIO()):
            run()
        self.assertEqual(self.locked.body_markdown, '# Exact Confluence title\n\n' + self.draft.body_markdown)
        self.assertIn(link, self.locked.body_markdown)
        self.assertEqual(self.locked.attributes['argus_summary'], 'This source introduction describes the modulator Ethernet connection.')
        self.assertEqual(self.locked.attributes['local'], 'keep')
        self.assertEqual(self.current.body_markdown, body)
        self.assertEqual(self.doc.current_revision_uid, 'published')
        self.db.add.assert_not_called()
        self.db.commit.assert_called_once()

    def test_presentation_preserves_existing_summary(self):
        run = self.setup_case(use=True, apply=True, presentation=True, already_fixed=True, summary='My own summary')
        with redirect_stdout(io.StringIO()):
            run()
        self.assertEqual(self.locked.attributes['argus_summary'], 'My own summary')

    def test_presentation_preserves_summary_saved_during_preview(self):
        run = self.setup_case(use=True, apply=True, presentation=True, already_fixed=True)
        self.locked.attributes['argus_summary'] = 'Newly saved summary'
        with redirect_stdout(io.StringIO()):
            run()
        self.assertEqual(self.locked.attributes['argus_summary'], 'Newly saved summary')
if __name__ == '__main__':
    unittest.main(verbosity=2)
