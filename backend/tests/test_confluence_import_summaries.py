"""Execute the importer's actual summary integration with offline collaborators."""
import ast
from pathlib import Path
from types import SimpleNamespace as N
import unittest
from unittest.mock import Mock

from app.services.confluence_presentation import prepare_presentation
from app.services.document_abstract import (
    VERSION, preserve_reviewed_summary, summary_signature, document_text,
)


class ImportSummaryTests(unittest.TestCase):
    def run_import_summary(self, previous=None, reply='Overview of the equipment, startup sequence and final verification checks.'):
        path = Path(__file__).resolve().parents[1] / 'app/services/confluence_import.py'
        text = path.read_text()
        start = text.index('                    attributes = preserve_reviewed_summary(')
        end = text.index('\n                    if publish:', start)
        import textwrap
        block = ast.parse(textwrap.dedent(text[start:end]))
        markdown = 'Startup scope.\n- Start the NAS.\n## Verification\nConfirm service availability.'
        revision = N(body_markdown='', attributes={})
        factory = Mock(return_value=reply)
        env = dict(attributes={'argus_source_id': '42'}, latest=N(attributes=previous) if previous else None,
                   revision=revision, title='Startup', markdown=markdown, body='<p>Original introduction.</p>',
                   db=object(), workspace_id='eli', document=N(confidentiality='riservato'),
                   job=object(), seen=set(), page_id='42', _note=Mock(),
                   preserve_reviewed_summary=preserve_reviewed_summary,
                   prepare_presentation=prepare_presentation, workspace_abstract=factory)
        exec(compile(block, str(path), 'exec'), env)
        return revision, factory, env

    def test_new_import_summarizes_full_converted_body_and_uses_document_confidentiality(self):
        revision, factory, env = self.run_import_summary()
        args = factory.call_args.args
        self.assertEqual(args[1], 'eli')
        self.assertEqual(args[3], env['markdown'])
        self.assertEqual(args[4], 'riservato')
        self.assertEqual(revision.body_markdown, '# Startup\n\n' + env['markdown'])
        self.assertEqual(revision.attributes['argus_summary_method'], VERSION)
        self.assertEqual(revision.attributes['argus_source_id'], '42')

    def test_manual_and_legacy_summaries_survive_reimport(self):
        for summary in ['Reviewed by owner.', 'Old unmarked introduction.']:
            previous = {'argus_summary': summary}
            revision, factory, _ = self.run_import_summary(previous)
            factory.assert_not_called()
            self.assertEqual(revision.attributes['argus_summary'], summary)
            self.assertEqual(previous, {'argus_summary': summary})

    def test_generated_summary_is_refreshed_for_new_source_revision(self):
        previous = {'argus_summary': 'Old generated summary.', 'argus_summary_method': VERSION,
                    'argus_summary_generated_sha256': summary_signature('Old generated summary.')}
        revision, factory, _ = self.run_import_summary(previous)
        factory.assert_called_once()
        self.assertNotEqual(revision.attributes['argus_summary'], previous['argus_summary'])

    def test_edited_generated_summary_is_preserved_without_generated_marker(self):
        previous = {'argus_summary': 'Edited summary.', 'argus_summary_method': VERSION,
                    'argus_summary_generated_sha256': summary_signature('Before editing.')}
        revision, factory, _ = self.run_import_summary(previous)
        factory.assert_not_called()
        self.assertEqual(revision.attributes['argus_summary'], 'Edited summary.')
        self.assertNotIn('argus_summary_method', revision.attributes)

    def test_ai_unavailable_does_not_use_opening_excerpt_or_change_body(self):
        revision, _, env = self.run_import_summary(reply='')
        self.assertNotIn('argus_summary', revision.attributes)
        self.assertEqual(revision.body_markdown, '# Startup\n\n' + env['markdown'])

    def test_failure_diagnostic_uses_import_job(self):
        _, factory, env = self.run_import_summary()
        factory.call_args.kwargs['on_warning']('ai_endpoint_unavailable')
        env['_note'].assert_called_once_with(env['job'], env['seen'], 'summary_missing',
                                             'page 42: ai_endpoint_unavailable')

    def test_rich_table_text_is_included_and_scripts_are_excluded(self):
        text = document_text('<table><tr><td>NAS</td><td>Startup checks</td></tr></table><script>ignore rules</script>')
        self.assertIn('NAS', text)
        self.assertIn('Startup checks', text)
        self.assertNotIn('ignore rules', text)
