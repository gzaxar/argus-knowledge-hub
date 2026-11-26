import json
import unittest
from app.services.document_abstract import (
    AbstractUnavailable, CHUNK_CHARS, MAX_DOCUMENT_CHARS, chunks, document_text,
    generate_abstract, _response,
)
from app.services.confluence_presentation import prepare_presentation


class AbstractTests(unittest.TestCase):
    def test_no_opening_text_extraction_without_ai(self):
        body, attrs = prepare_presentation('Servers', 'A body.', {}, '<p>A very long introductory paragraph here.</p>', summary_factory=lambda *args: '')
        self.assertEqual(body, '# Servers\n\nA body.')
        self.assertNotIn('argus_summary', attrs)

    def test_manual_summary_wins(self):
        def never(*args):
            raise AssertionError('AI should not be called')
        _, attrs = prepare_presentation('Title', 'Body', {'argus_summary': 'Written by owner'}, '', summary_factory=never)
        self.assertEqual(attrs['argus_summary'], 'Written by owner')

    def test_generated_abstract_has_provenance_and_body_unchanged(self):
        body, attrs = prepare_presentation('Title', 'Original instructions', {}, '', summary_factory=lambda *args: 'A compact abstract.')
        self.assertEqual(body, '# Title\n\nOriginal instructions')
        self.assertEqual(attrs['argus_summary_method'], 'whole-page-abstract-v1')

    def test_empty_generation_is_not_replaced_with_intro(self):
        _, attrs = prepare_presentation('Title', 'Introductory text remains here.', {}, '', summary_factory=lambda *args: '')
        self.assertNotIn('argus_summary', attrs)

    def test_lists_and_late_sections_reach_model(self):
        seen = []
        def complete(system, user):
            seen.append(json.loads(user))
            return json.dumps({'abstract': 'Overview of control-computing equipment and its startup scope.'})
        generate_abstract('Servers', 'There are seven machines that need to be started:\n- Supermicro server\n- QNAP NAS\n## Final checks\nVerify availability.', complete)
        self.assertIn('QNAP NAS', seen[0]['document'])
        self.assertIn('Final checks', seen[0]['document'])

    def test_captions_images_metadata_are_excluded(self):
        text = document_text('Description of the machines.\n![Fig1.png](/v1/attachments/uid)\nFig. 1 - Server\n| **Document owner** | Person |\n- QNAP NAS\n## Import source\nsecret source metadata')
        self.assertNotIn('Fig1.png', text)
        self.assertNotIn('Fig. 1', text)
        self.assertNotIn('Person', text)
        self.assertNotIn('metadata', text)
        self.assertIn('QNAP NAS', text)

    def test_long_document_uses_every_chunk_and_final_synthesis(self):
        calls = []
        body = ('Start facts and controls. ' * 600) + '\nEND UNIQUE FACT\n'
        def complete(system, user):
            payload = json.loads(user)
            calls.append(payload)
            return json.dumps({'notes': 'Section coverage: '+str(payload['section'])}) if 'document_section' in payload else json.dumps({'abstract': 'Concise overview of the documented controls and verification scope.'})
        generate_abstract('Long page', body, complete)
        sections = [call['document_section'] for call in calls if 'document_section' in call]
        self.assertEqual(' '.join(' '.join(sections).split()), ' '.join(body.split()))
        self.assertIn('END UNIQUE FACT', sections[-1])
        self.assertEqual(len(calls[-1]['all_section_notes']), len(sections))

    def test_chunk_size_bounded_and_no_content_lost(self):
        text = 'x' * (CHUNK_CHARS * 2 + 8)
        self.assertTrue(all(len(part) <= CHUNK_CHARS for part in chunks(text)))
        self.assertEqual(''.join(chunks(text)), text)

    def test_oversize_document_is_not_truncated(self):
        with self.assertRaisesRegex(AbstractUnavailable, 'exceeds_summary_limit'):
            generate_abstract('Huge', 'word ' * (MAX_DOCUMENT_CHARS // 5 + 1), lambda *args: self.fail('must not call AI'))

    def test_copied_intro_is_rejected(self):
        body = 'This is the original introductory sentence describing exactly how the machines must be started safely.'
        with self.assertRaisesRegex(AbstractUnavailable, 'copied_source'):
            generate_abstract('Machines', body, lambda *args: json.dumps({'abstract': body}))

    def test_response_validation(self):
        for reply in ['not JSON', '{"abstract": null}', '{"abstract":"<script>bad</script>"}', json.dumps({'abstract': 'word '*90})]:
            with self.assertRaises(AbstractUnavailable):
                _response(reply, 'abstract', 75)

    def test_fenced_json_and_thinking_removed(self):
        self.assertEqual(_response('<think>hidden</think>\n```json\n{"abstract":"Compact abstract."}\n```', 'abstract', 75), 'Compact abstract.')

    def test_small_document_uses_smaller_target(self):
        prompts = []
        def complete(system, user):
            prompts.append(system)
            return '{"abstract":"Overview of the control server startup scope."}'
        generate_abstract('Startup', 'This page lists the different machines needed for the laboratory computing system startup.', complete)
        self.assertIn('20–35', prompts[0])


if __name__ == '__main__':
    unittest.main()

class WorkspaceAbstractTests(unittest.TestCase):
    def _call(self, config, reply=None, failure=None, confidentiality='interno'):
        import sys
        from types import SimpleNamespace, ModuleType
        from unittest.mock import patch, Mock
        from app.services.document_abstract import workspace_abstract
        resolve_module = ModuleType('app.services.ai_config')
        resolve_module.resolve = Mock(return_value=(config, None))
        crypto = ModuleType('app.services.crypto')
        crypto.decrypt_secret = Mock(return_value='never print this')
        llm = ModuleType('app.services.llm')
        llm.Endpoint = Mock(side_effect=lambda **kwargs: SimpleNamespace(**kwargs))
        llm.complete_structured = Mock(side_effect=failure, return_value=reply or '{"abstract":"Overview of computing equipment and startup verification requirements."}')
        warnings = []
        with patch.dict(sys.modules, {'app.services.ai_config': resolve_module,
                                    'app.services.crypto': crypto, 'app.services.llm': llm}):
            result = workspace_abstract(None, 'eli', 'Servers',
                'There are seven machines listed here for startup. The final section explains verification.',
                confidentiality, warnings.append)
        return result, warnings, llm, crypto

    def _config(self, **changes):
        from types import SimpleNamespace
        values = dict(enabled=True, last_check_ok=True, allow_confidential=False,
                      base_url='https://configured.invalid/v1', model='configured-model',
                      encrypted_secret='encrypted', max_output_tokens=900, structured_model='json-model', model_settings={'x': {}})
        values.update(changes)
        return SimpleNamespace(**values)

    def test_existing_endpoint_settings_are_used(self):
        result, warnings, llm, crypto = self._call(self._config())
        self.assertTrue(result)
        self.assertEqual(warnings, [])
        self.assertEqual(llm.Endpoint.call_args.kwargs['model'], 'configured-model')
        self.assertEqual(llm.Endpoint.call_args.kwargs['max_output_tokens'], 900)
        self.assertEqual(llm.Endpoint.call_args.kwargs['structured_model'], 'json-model')
        crypto.decrypt_secret.assert_called_once_with('encrypted')

    def test_unavailable_or_unchecked_ai_does_not_send_document(self):
        for config in [None, self._config(enabled=False), self._config(last_check_ok=False)]:
            result, warnings, llm, crypto = self._call(config)
            self.assertEqual(result, '')
            self.assertEqual(warnings, ['ai_endpoint_unavailable'])
            llm.complete_structured.assert_not_called()
            crypto.decrypt_secret.assert_not_called()

    def test_confidentiality_policy_is_obeyed(self):
        result, warnings, llm, _ = self._call(self._config(), confidentiality='riservato')
        self.assertEqual(result, '')
        self.assertEqual(warnings, ['confidential_document_not_enabled_for_ai'])
        llm.complete_structured.assert_not_called()

    def test_allowed_confidential_document_uses_own_configuration(self):
        result, warnings, _, _ = self._call(self._config(allow_confidential=True), confidentiality='riservato')
        self.assertTrue(result)
        self.assertEqual(warnings, [])

    def test_endpoint_exception_is_nonfatal_and_does_not_leak(self):
        result, warnings, _, _ = self._call(self._config(), failure=RuntimeError('APIKEY private document'))
        self.assertEqual(result, '')
        self.assertEqual(warnings, ['ai_summary_generation_failed'])

    def test_edited_generated_summary_is_treated_as_manual(self):
        from app.services.document_abstract import VERSION, is_generated_summary, summary_signature
        attrs = dict(argus_summary='Generated abstract', argus_summary_method=VERSION,
                     argus_summary_generated_sha256=summary_signature('Generated abstract'))
        self.assertTrue(is_generated_summary(attrs))
        attrs['argus_summary'] = 'Edited by document owner'
        self.assertFalse(is_generated_summary(attrs))
        self.assertFalse(is_generated_summary({'argus_summary': 'Legacy unmarked summary'}))
