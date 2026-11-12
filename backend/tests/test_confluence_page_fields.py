"""Pure/fake-session checks; no real Confluence requests or database writes."""
import unittest

from app.services.confluence_page_fields import (
    normalize_document_status, render_user_mentions, resolve_user_names, status_html, user_identity, user_references,
)


class Response:
    def __init__(self, status=200, data=None):
        self.status_code, self.data = status, data


class Session:
    def __init__(self, response=None, raises=False):
        self.response, self.raises, self.calls = response or Response(), raises, []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.raises:
            raise RuntimeError('Network failure')
        return self.response


def read_json(response):
    return response.data


class PageFieldsTests(unittest.TestCase):
    def test_status_title_preserved(self):
        self.assertEqual(status_html('<ac:structured-macro ac:name="status"><ac:parameter ac:name="title">IN PROGRESS</ac:parameter><ac:parameter ac:name="colour">Yellow</ac:parameter></ac:structured-macro>'), '<span>IN PROGRESS</span>')

    def test_status_single_quoted_parameter(self):
        self.assertEqual(status_html("<ac:parameter ac:name='title'>DRAFT</ac:parameter>"), '<span>DRAFT</span>')

    def test_status_cdata(self):
        self.assertEqual(status_html('<ac:parameter ac:name="title"><![CDATA[IN PROGRESS]]></ac:parameter>'), '<span>IN PROGRESS</span>')

    def test_status_entities_and_markup_are_escaped(self):
        self.assertEqual(status_html('<ac:parameter ac:name="title">A &amp; B &lt;test&gt;</ac:parameter>'), '<span>A &amp; B &lt;test&gt;</span>')

    def test_status_title_not_inferred_from_colour(self):
        self.assertIn('Source status unavailable', status_html('<ac:parameter ac:name="colour">Green</ac:parameter>'))
        self.assertNotIn('Approved', status_html(''))

    def test_cloud_identity(self):
        self.assertEqual(user_identity('<ri:user ri:account-id="abc:123" />'), ('accountId', 'abc:123'))

    def test_server_key_and_username(self):
        self.assertEqual(user_identity('<ri:user ri:userkey="key1" />'), ('key', 'key1'))
        self.assertEqual(user_identity('<ri:user ri:username="user1"></ri:user>'), ('username', 'user1'))

    def test_identity_decodes_entities_and_prefers_account_id(self):
        self.assertEqual(user_identity('<ri:user ri:account-id="a&amp;b" ri:userkey="old"/>'), ('accountId', 'a&b'))

    def test_invalid_identity_not_looked_up(self):
        self.assertIsNone(user_identity('<ri:user ri:account-id="&#10;" />'))
        self.assertEqual(user_references('<ri:user />'), [])
        self.assertIn('Unresolved Confluence user', render_user_mentions('<ri:user />'))

    def test_duplicate_mentions_deduplicated_for_requests(self):
        self.assertEqual(user_references('<ri:user ri:userkey="a"/><ri:user ri:userkey="a"/><ri:user ri:userkey="b"/>'), [('key', 'a'), ('key', 'b')])

    def test_cloud_resolution_uses_site_session_and_query_parameter(self):
        session = Session(Response(data={'accountId': 'abc', 'displayName': 'Fabio Cardelli', 'email': 'not-retained@example.invalid'}))
        cache = {}
        result = resolve_user_names('<ri:user ri:account-id="abc"/>', session, 'https://example.atlassian.net/wiki/', cache, read_json)
        self.assertEqual(result, {('accountId', 'abc'): 'Fabio Cardelli'})
        self.assertEqual(session.calls, [('https://example.atlassian.net/wiki/rest/api/user', {'params': {'accountId': 'abc'}, 'allow_redirects': False})])
        self.assertEqual(cache, {('accountId', 'abc'): 'Fabio Cardelli'})

    def test_success_cache_reused_across_pages(self):
        session = Session(Response(data={'displayName': 'Owner'}))
        cache = {}
        for _ in range(2):
            resolve_user_names('<ri:user ri:userkey="a"/>', session, 'https://example/wiki', cache, read_json)
        self.assertEqual(len(session.calls), 1)

    def test_permission_failure_is_cached_and_warned(self):
        session = Session(Response(status=403))
        cache, warnings = {}, []
        for _ in range(2):
            self.assertEqual(resolve_user_names('<ri:user ri:account-id="abc"/>', session, 'https://example/wiki', cache, read_json, warnings.append), {})
        self.assertEqual(len(session.calls), 1)
        self.assertTrue(warnings)

    def test_network_failure_does_not_fail_page(self):
        session = Session(raises=True)
        warnings = []
        self.assertEqual(resolve_user_names('<ri:user ri:userkey="abc"/>', session, 'https://example/wiki', {}, read_json, warnings.append), {})
        self.assertTrue(warnings)

    def test_html_login_instead_of_json_is_not_a_user_name(self):
        session = Session(Response(data='<html>Login</html>'))
        self.assertEqual(resolve_user_names('<ri:user ri:userkey="abc"/>', session, 'https://example/wiki', {}, read_json), {})

    def test_wrong_returned_identity_is_rejected(self):
        session = Session(Response(data={'accountId': 'different', 'displayName': 'Wrong person'}))
        self.assertEqual(resolve_user_names('<ri:user ri:account-id="abc"/>', session, 'https://example/wiki', {}, read_json), {})

    def test_public_name_fallback(self):
        session = Session(Response(data={'publicName': 'Visible name'}))
        self.assertEqual(resolve_user_names('<ri:user ri:userkey="abc"/>', session, 'https://example/wiki', {}, read_json), {('key', 'abc'): 'Visible name'})

    def test_lookup_limit(self):
        session = Session()
        warnings = []
        self.assertEqual(resolve_user_names('<ri:user ri:userkey="abc"/>', session, 'https://example/wiki', {}, read_json, warnings.append, max_users=0), {})
        self.assertFalse(session.calls)
        self.assertTrue(warnings)

    def test_display_name_rendered_as_text_not_html(self):
        html = render_user_mentions('<ri:user ri:account-id="abc"/>', {('accountId', 'abc'): 'A & B <script>'})
        self.assertEqual(html, '<span>A &amp; B &lt;script&gt;</span>')

    def test_multiple_owners_keep_source_separator(self):
        html = render_user_mentions('<ri:user ri:userkey="a"/> - <ri:user ri:userkey="b"/>', {('key', 'a'): 'Giovanni', ('key', 'b'): 'Georgios'})
        self.assertEqual(html, '<span>Giovanni</span> - <span>Georgios</span>')

    def test_unresolved_mention_is_explicit(self):
        html = render_user_mentions('<ri:user ri:userkey="missing"/>')
        self.assertIn('Unresolved Confluence user (key: missing)', html)
        self.assertNotIn('ri:', html)

    def test_linked_user_not_rendered_twice(self):
        html = render_user_mentions('<ac:link><ri:user ri:userkey="a"/><ac:plain-text-link-body><![CDATA[Name]]></ac:plain-text-link-body></ac:link>', {('key', 'a'): 'Name'})
        self.assertEqual(html, '<span>Name</span>')

    def test_code_and_comments_not_resolved_or_rewritten(self):
        for body in ('<ac:plain-text-body><![CDATA[<ri:user ri:userkey="sample"/>]]></ac:plain-text-body>', '<pre><ri:user ri:userkey="sample"/></pre>', '<code><ri:user ri:userkey="sample"/></code>', '<!-- <ri:user ri:userkey="sample"/> -->'):
            self.assertEqual(user_references(body), [])
            self.assertEqual(render_user_mentions(body), body)

    def test_plain_owner_text_untouched(self):
        self.assertEqual(render_user_mentions('<td>Giovanni - Georgios</td>'), '<td>Giovanni - Georgios</td>')



class StatusPromptTests(unittest.TestCase):
    def test_reported_optical_fanout_row(self):
        self.assertEqual(normalize_document_status('| **Document status** | SET a STATUS IN PROGRESS |'), '| **Document status** | IN PROGRESS |')

    def test_correct_diagnostics_row_unchanged(self):
        row = '| **Document status** | In progress |'
        self.assertEqual(normalize_document_status(row), row)

    def test_actual_status_case_preserved(self):
        self.assertEqual(normalize_document_status('| Document status | Set a status In progress |'), '| Document status | In progress |')

    def test_prose_and_other_cells_unchanged(self):
        text = 'Set a status IN PROGRESS.\n| Instruction | SET a STATUS IN PROGRESS |'
        self.assertEqual(normalize_document_status(text), text)

    def test_code_examples_unchanged(self):
        for text in ('```md\n| Document status | SET a STATUS IN PROGRESS |\n```', '~~~\n| Document status | SET a STATUS IN PROGRESS |\n~~~', '    | Document status | SET a STATUS IN PROGRESS |'):
            self.assertEqual(normalize_document_status(text), text)

    def test_placeholder_without_actual_status_is_not_an_approval(self):
        result = normalize_document_status('| Document status | SET a STATUS |')
        self.assertIn('Source status unavailable', result)
        self.assertNotIn('APPROVED', result)

    def test_similar_words_not_removed(self):
        row = '| Document status | SET a STATUSFUL value |'
        self.assertEqual(normalize_document_status(row), row)

    def test_line_endings_preserved(self):
        self.assertEqual(normalize_document_status('| Document status | SET a STATUS IN PROGRESS |\r\n'), '| Document status | IN PROGRESS |\r\n')

    def test_idempotent(self):
        result = normalize_document_status('| Document status | SET a STATUS IN PROGRESS |')
        self.assertEqual(normalize_document_status(result), result)

    def test_prompt_after_real_status_not_removed(self):
        row = '| Document status | IN PROGRESS SET a STATUS |'
        self.assertEqual(normalize_document_status(row), row)


class OwnerSeparatorTests(unittest.TestCase):
    names = {('key', 'a'): 'Giovanni Franzini', ('key', 'b'): 'Georgios Zachariadis', ('key', 'c'): 'Fabio Cardelli'}

    def row(self, value, label='Document owner'):
        return f'<table><tr><td><strong>{label}</strong></td><td><p>{value}</p></td></tr></table>'

    def test_two_linked_owners(self):
        html = self.row('<ac:link><ri:user ri:userkey="a"/></ac:link> <ac:link><ri:user ri:userkey="b"/></ac:link>')
        self.assertIn('<span>Giovanni Franzini</span> - <span>Georgios Zachariadis</span>', render_user_mentions(html, self.names))

    def test_three_owners_without_separators(self):
        html = self.row('<ri:user ri:userkey="a"/><ri:user ri:userkey="b"/> <ri:user ri:userkey="c"/>')
        result = render_user_mentions(html, self.names)
        self.assertEqual(result.count(' - '), 2)

    def test_existing_separator_not_duplicated(self):
        html = self.row('<ri:user ri:userkey="a"/> - <ri:user ri:userkey="b"/>')
        self.assertEqual(render_user_mentions(html, self.names).count(' - '), 1)

    def test_break_and_nonbreaking_space_between_owners(self):
        html = self.row('<ri:user ri:userkey="a"/>&nbsp;<br/> <ri:user ri:userkey="b"/>')
        self.assertIn('</span> - <span>', render_user_mentions(html, self.names))

    def test_mentions_in_other_cells_not_joined(self):
        html = self.row('<ri:user ri:userkey="a"/> <ri:user ri:userkey="b"/>', label='Reviewers')
        self.assertNotIn(' - ', render_user_mentions(html, self.names))

    def test_mentions_in_prose_not_joined(self):
        html = '<p><ri:user ri:userkey="a"/> <ri:user ri:userkey="b"/></p>'
        self.assertNotIn(' - ', render_user_mentions(html, self.names))

    def test_plain_text_names_not_split_on_spaces(self):
        html = self.row('Giovanni Franzini Georgios Zachariadis')
        self.assertEqual(render_user_mentions(html, self.names), html)

    def test_mixed_link_and_standalone_mention(self):
        html = self.row('<ac:link><ri:user ri:userkey="a"/></ac:link> <ri:user ri:userkey="b"/>')
        self.assertIn('</span> - <span>', render_user_mentions(html, self.names))

if __name__ == '__main__':
    unittest.main()
