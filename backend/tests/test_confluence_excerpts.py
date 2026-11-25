"""Synthetic fixtures only: no exported pages, network addresses or credentials."""
import ast
from pathlib import Path
from types import SimpleNamespace as N
import unittest
from unittest.mock import Mock

from app.services.confluence_excerpts import ExcerptResolver, authenticated_resolver, missing_excerpt


def include(title='Shared settings', name='network', space='', extra=''):
    return ('<ac:structured-macro ac:name="excerpt-include"><ac:parameter ac:name="">'
            '<ac:link><ri:page ri:content-title="' + title + '" ri:space-key="' + space + '" />'
            '</ac:link></ac:parameter><ac:parameter ac:name="name">' + name + '</ac:parameter>'
            + extra + '</ac:structured-macro>')


def excerpt(name='network', body='<p>control-lab</p>'):
    return ('<ac:structured-macro ac:name="excerpt"><ac:parameter ac:name="name">' + name
            + '</ac:parameter><ac:rich-text-body>' + body
            + '</ac:rich-text-body></ac:structured-macro>')


def page(body, uid='100', title='Shared settings', space='TEST'):
    return {'id': uid, 'title': title, 'space': {'key': space}, 'body': {'storage': {'value': body}}}


class ExcerptTests(unittest.TestCase):
    def resolver(self, body=None):
        fetch = Mock(return_value=page(body if body is not None else excerpt()))
        warnings = []
        return ExcerptResolver(fetch, warnings.append), fetch, warnings

    def test_named_excerpt_in_original_position_without_other_page_content(self):
        resolver, _, warnings = self.resolver('<h2>Private unrelated text</h2>' + excerpt() + excerpt('other', '<p>other value</p>'))
        result = resolver.resolve('<h2>Address table</h2>' + include() + '<table><tr><td>PSU</td></tr></table>', 'TEST')
        self.assertIn('Shared settings | network', result)
        self.assertIn('<p>control-lab</p>', result)
        self.assertLess(result.index('control-lab'), result.index('<table>'))
        self.assertNotIn('unrelated', result)
        self.assertNotIn('other value', result)
        self.assertEqual(warnings, [])

    def test_named_excerpt_and_cache(self):
        resolver, fetch, _ = self.resolver()
        resolver.resolve(include() * 2, 'TEST')
        fetch.assert_called_once_with('TEST', 'Shared settings', '')

    def test_explicit_space_and_no_frame(self):
        resolver, fetch, _ = self.resolver()
        result = resolver.resolve(include(space='OTHER', extra='<ac:parameter ac:name="nopanel">true</ac:parameter>'), 'TEST')
        fetch.assert_called_once_with('OTHER', 'Shared settings', '')
        self.assertEqual(result, '<p>control-lab</p>')

    def test_unnamed_excerpt(self):
        resolver, _, _ = self.resolver(excerpt(''))
        self.assertIn('control-lab', resolver.resolve(include(name=''), 'TEST'))

    def test_nested_macro_body_is_complete(self):
        body = '<p>before</p><ac:structured-macro ac:name="info"><ac:rich-text-body><p>nested</p></ac:rich-text-body></ac:structured-macro><p>after</p>'
        resolver, _, _ = self.resolver(excerpt(body=body))
        result = resolver.resolve(include(), 'TEST')
        self.assertIn(body, result)

    def test_nested_include_and_cycle_are_bounded(self):
        resolver, _, warnings = self.resolver(excerpt(body=include()))
        result = resolver.resolve(include(), 'TEST')
        self.assertIn('excerpt unavailable', result)
        self.assertIn('excerpt_cycle', warnings)

    def test_missing_or_ambiguous_named_excerpt_has_visible_fallback(self):
        for body in [excerpt('different'), excerpt() + excerpt()]:
            resolver, _, warnings = self.resolver(body)
            result = resolver.resolve(include(), 'TEST')
            self.assertIn('Shared settings | network', result)
            self.assertIn('unavailable', result)
            self.assertEqual(warnings, ['excerpt_not_found_or_ambiguous'])

    def test_denied_fetch_is_nonfatal_and_exception_details_are_not_leaked(self):
        resolver, fetch, warnings = self.resolver()
        fetch.side_effect = RuntimeError('private API key and response body')
        result = resolver.resolve(include() * 2, 'TEST')
        self.assertIn('unavailable', result)
        self.assertNotIn('API key', result)
        self.assertEqual(warnings, ['excerpt_page_unavailable'] * 2)
        fetch.assert_called_once()

    def test_fetch_depth_and_size_limits_are_visible(self):
        resolver, _, warnings = self.resolver()
        resolver.MAX_FETCHES = 0
        self.assertIn('unavailable', resolver.resolve(include(), 'TEST'))
        self.assertEqual(warnings, ['excerpt_fetch_limit'])
        resolver, _, warnings = self.resolver()
        resolver.MAX_DEPTH = 0
        resolver.resolve(include(), 'TEST')
        self.assertEqual(warnings, ['excerpt_depth_limit'])
        resolver, _, warnings = self.resolver()
        resolver.MAX_PAGE_CHARS = 2
        resolver.resolve(include(), 'TEST')
        self.assertEqual(warnings, ['excerpt_page_size_limit'])
        resolver, _, warnings = self.resolver()
        resolver.MAX_EXPANSION_CHARS = 2
        resolver.resolve(include(), 'TEST')
        self.assertEqual(warnings, ['excerpt_expansion_size_limit'])

    def test_excerpt_files_never_bind_to_receiving_page_files(self):
        resolver, _, warnings = self.resolver(excerpt(body='<p>value</p><ac:image><ri:attachment ri:filename="file.png" /></ac:image>'))
        self.assertIn('unavailable', resolver.resolve(include(), 'TEST'))
        self.assertEqual(warnings, ['excerpt_attachments_not_supported'])

    def test_fallback_is_escaped(self):
        self.assertIn('&lt;img', missing_excerpt(include(title='&lt;img src=x&gt;')))

    def test_authentication_session_and_fixed_origin_are_reused(self):
        response = Mock()
        session = Mock(get=Mock(return_value=response))
        read = Mock(return_value={'results': [page(excerpt())]})
        resolver = authenticated_resolver(session, 'https://wiki.invalid/wiki', read)
        self.assertIn('control-lab', resolver.resolve(include(), 'TEST'))
        self.assertEqual(session.get.call_args.args, ('https://wiki.invalid/wiki/rest/api/content',))
        self.assertEqual(session.get.call_args.kwargs['params']['spaceKey'], 'TEST')
        self.assertEqual(session.get.call_args.kwargs['params']['title'], 'Shared settings')
        response.raise_for_status.assert_called_once()

    def test_malicious_reference_does_not_change_request_destination(self):
        session = Mock()
        resolver = authenticated_resolver(session, 'https://wiki.invalid/wiki', lambda r: {'results': []})
        resolver.resolve(include(title='https://other.invalid/private'), 'TEST')
        self.assertEqual(session.get.call_args.args[0], 'https://wiki.invalid/wiki/rest/api/content')

    def test_content_id_reference(self):
        session = Mock()
        resolver = authenticated_resolver(session, 'https://wiki.invalid/wiki', lambda r: page(excerpt()))
        storage = include().replace('ri:content-title="Shared settings"', 'ri:content-id="100"')
        self.assertIn('control-lab', resolver.resolve(storage, 'TEST'))
        self.assertEqual(session.get.call_args.args[0], 'https://wiki.invalid/wiki/rest/api/content/100')

    def test_static_converter_keeps_unresolved_reference_visible(self):
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / 'app/services/confluence_import.py').read_text())
        names = {'_macro_param', '_macro_body', '_convert_macro'}
        module = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])
        import re
        env = dict(re=re, Optional=__import__('typing').Optional, FILE_VIEWER_MACROS=set(),
                   _PANEL_MACROS={}, missing_excerpt=missing_excerpt)
        exec(compile(module, '<converter>', 'exec'), env)
        match = re.match(r'<ac:structured-macro ac:name="([^"]+)".*', include())
        self.assertIn('Shared settings | network', env['_convert_macro'](match))

    def test_importer_resolves_before_user_names_conversion_and_summary(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / 'app/services/confluence_import.py').read_text()
        start = source.index('                    if base_url not in excerpt_resolvers:')
        end = source.index('                    user_names = resolve_user_names(', start)
        import textwrap
        warnings = Mock()
        resolver = ExcerptResolver(lambda *args: page(excerpt()))
        factory = Mock(return_value=resolver)
        env = dict(base_url='https://wiki.invalid/wiki', excerpt_resolvers={},
                   authenticated_resolver=factory, session=object(), confluence_json=Mock(),
                   _note=warnings, job=object(), seen=set(), body=include(), space='TEST', page_id='42')
        exec(compile(textwrap.dedent(source[start:end]), '<importer>', 'exec'), env)
        self.assertIn('control-lab', env['body'])
        factory.assert_called_once()
