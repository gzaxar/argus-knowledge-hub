"""Isolated checks of the actual repair function with in-memory collaborators.

The function AST is loaded to avoid importing the full application/SQLAlchemy
runtime. These checks exercise decision logic, not ORM/database integration.
Run after installing the first file-link update and this follow-up.
"""
import ast,sys,uuid,unittest,io,re
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace as N
from unittest.mock import MagicMock
from urllib.parse import urlparse
from contextlib import redirect_stdout
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from app.services.confluence_file_macros import FILE_VIEWER_MACROS,render_file_macro,replace_file_viewer_placeholders
pattern=re.compile(r'<ac:structured-macro[^>]*ac:name="([^"]+)"(?:(?!<ac:structured-macro).)*?</ac:structured-macro>',re.S)
macro='<ac:structured-macro ac:name="view-file"><ac:parameter ac:name="name"><ri:attachment ri:filename="cx2000_en.pdf" /></ac:parameter></ac:structured-macro>'
marker='*[view-file — see the original page]*';link='[cx2000_en.pdf](/v1/attachments/file)';body='Published intro\n'+marker+'\nManual'
tree=ast.parse((root/'app/services/confluence_file_repair.py').read_text());tree.body=[n for n in tree.body if getattr(n,'name',None)=='repair']
class DraftRepairChecks(unittest.TestCase):
 def setup_case(self,apply=False,state='draft',use=False,open_exists=True,changed=False,version=8,already_fixed=False):
  doc=N(uid='doc',code='CONF-117374977',title='Modulator',current_revision_uid='published')
  current=N(uid='published',state='published',body_markdown=body,attributes={'argus_source_id':'117374977','argus_source_version':8,'argus_source_url':'https://site.atlassian.net/wiki/pages/viewpage.action?pageId=117374977'},steps=['preserve'],valid_from=None,valid_until=None,next_review_due=None)
  draft=N(uid='draft',state=state,body_markdown='My saved edits\n'+(link if already_fixed else marker)+'\nManual',attributes={'local':'keep'},steps=['edited'])
  locked=deepcopy(draft)
  if changed:locked.body_markdown+='Someone edited this'
  config=N(params={'base_url':'https://site.atlassian.net/wiki','auth_mode':'cloud_basic','email':'u@example.org'},encrypted_secret='cipher',name='test')
  db=MagicMock();db.execute.return_value.all.return_value=[(doc,current)]
  db.scalars.side_effect=[N(all=lambda:[draft] if open_exists else []),N(all=lambda:[config]),N(all=lambda:[N(filename='cx2000_en.pdf',uid='file')]),N(all=lambda:[locked] if open_exists else [])]
  db.scalar.side_effect=[doc,1];db.get.return_value=current
  model=MagicMock();model.side_effect=lambda **kw:N(**kw)
  page={'id':'117374977','version':{'number':version},'body':{'storage':{'value':macro}}}
  env=dict(SessionLocal=lambda:db,select=lambda *a:MagicMock(),func=MagicMock(),Document=MagicMock(),DocumentRevision=model,ImportConfig=MagicMock(),Attachment=MagicMock(),parse_page_link=lambda x:{'base_url':'https://site.atlassian.net/wiki'},urlparse=urlparse,decrypt_secret=lambda x:'not-printed',_TimeoutSession=lambda:N(get=lambda *a,**kw:page,close=lambda:None),configure_confluence_session=lambda s,b,*a:b,resolve_api_base=lambda s,b:b,confluence_json=lambda r:r,_INNERMOST_MACRO=pattern,FILE_VIEWER_MACROS=FILE_VIEWER_MACROS,render_file_macro=render_file_macro,storage_to_markdown=lambda *a:link,replace_file_viewer_placeholders=replace_file_viewer_placeholders,deepcopy=deepcopy,uuid=uuid)
  exec(compile(tree,'repair','exec'),env)
  self.db=db;self.current=current;self.doc=doc;self.draft=draft;self.locked=locked
  return lambda:env['repair']('eli','117374977',apply=apply,use_existing_draft=use)
 def test_draft_requires_explicit_option(self):
  run=self.setup_case()
  with self.assertRaisesRegex(ValueError,'--use-existing-draft'),redirect_stdout(io.StringIO()):run()
  self.db.commit.assert_not_called()
 def test_draft_preview_never_writes(self):
  run=self.setup_case(use=True)
  with redirect_stdout(io.StringIO()):run()
  self.db.commit.assert_not_called();self.db.add.assert_not_called();self.assertEqual(self.locked.body_markdown,self.draft.body_markdown)
 def test_draft_apply_preserves_other_content_and_identity(self):
  run=self.setup_case(use=True,apply=True)
  with redirect_stdout(io.StringIO()):run()
  self.assertEqual(self.locked.body_markdown,self.draft.body_markdown.replace(marker,link))
  self.assertEqual(self.locked.attributes,{'local':'keep'});self.assertEqual(self.locked.steps,['edited'])
  self.assertEqual(self.locked.uid,'draft');self.assertEqual(self.locked.state,'draft')
  self.assertEqual(self.current.body_markdown,body);self.assertEqual(self.doc.current_revision_uid,'published')
  self.db.add.assert_not_called();self.db.commit.assert_called_once()
 def test_in_review_refused(self):
  run=self.setup_case(use=True,apply=True,state='in_review')
  with self.assertRaisesRegex(ValueError,'in review or approved'),redirect_stdout(io.StringIO()):run()
  self.db.commit.assert_not_called()
 def test_approved_refused(self):
  run=self.setup_case(use=True,apply=True,state='approved')
  with self.assertRaisesRegex(ValueError,'in review or approved'),redirect_stdout(io.StringIO()):run()
  self.db.commit.assert_not_called()
 def test_concurrent_body_edit_refused(self):
  run=self.setup_case(use=True,apply=True,changed=True)
  with self.assertRaisesRegex(ValueError,'draft changed'),redirect_stdout(io.StringIO()):run()
  self.db.commit.assert_not_called()
 def test_changed_source_refused(self):
  run=self.setup_case(use=True,apply=True,version=9)
  with self.assertRaisesRegex(ValueError,'source page/version'),redirect_stdout(io.StringIO()):run()
  self.db.commit.assert_not_called()
 def test_new_draft_creation_still_works(self):
  run=self.setup_case(apply=True,open_exists=False)
  with redirect_stdout(io.StringIO()):run()
  self.assertEqual(self.db.add.call_args.args[0].state,'draft');self.db.commit.assert_called_once()
 def test_explicit_flag_requires_existing_draft(self):
  run=self.setup_case(use=True,open_exists=False)
  with self.assertRaisesRegex(ValueError,'No editable draft'),redirect_stdout(io.StringIO()):run()
  self.db.commit.assert_not_called()
 def test_repaired_draft_is_noop(self):
  run=self.setup_case(use=True,apply=True,already_fixed=True)
  with redirect_stdout(io.StringIO()):run()
  self.db.commit.assert_not_called();self.db.add.assert_not_called()
if __name__=='__main__':unittest.main(verbosity=2)
