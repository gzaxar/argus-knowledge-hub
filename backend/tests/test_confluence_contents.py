"""Pure TOC conversion checks, also runnable with Python's unittest runner."""
import unittest
from urllib.parse import unquote

from app.services.confluence_contents import collect_headings, heading_slug, render_contents, toc_placeholder


class ContentsTests(unittest.TestCase):
    def render(self, html, block='<ac:structured-macro ac:name="toc" />', title=None, body=None):
        slots = {}
        toc_placeholder(block, slots)
        marker = next(iter(slots))
        return render_contents(body if body is not None else f'Before\n\n{marker}\n\nAfter', slots, collect_headings(html), title)

    def test_contents_at_macro_position(self):
        result = self.render('<h2>Goals</h2><h2>Resources</h2><h3>Manuals</h3>')
        self.assertEqual(result, 'Before\n\n- [Goals](#argus-heading-goals)\n- [Resources](#argus-heading-resources)\n  - [Manuals](#argus-heading-manuals)\n\nAfter')

    def test_minimum_and_maximum_levels(self):
        result = self.render('<h1>Title</h1><h2>Goals</h2><h3>Manuals</h3><h4>PDF</h4>',
                             '<ac:parameter ac:name="minLevel">2</ac:parameter><ac:parameter ac:name="maxLevel">3</ac:parameter>')
        self.assertIn('[Goals]', result)
        self.assertIn('  - [Manuals]', result)
        self.assertNotIn('[Title]', result)
        self.assertNotIn('[PDF]', result)

    def test_duplicate_headings(self):
        result = self.render('<h2>Goals</h2><h2>Goals</h2>')
        self.assertIn('(#argus-heading-goals)', result)
        self.assertIn('(#argus-heading-goals-1)', result)

    def test_hidden_headings_still_consume_duplicate_ids(self):
        result = self.render('<h1>Goals</h1><h2>Goals</h2>', '<ac:parameter ac:name="minLevel">2</ac:parameter>')
        self.assertIn('(#argus-heading-goals-1)', result)

    def test_generated_title_reserves_its_heading_id(self):
        result = self.render('<h2>Goals</h2>', title='Goals')
        self.assertIn('(#argus-heading-goals-1)', result)

    def test_existing_title_is_not_counted_twice(self):
        slots = {}
        toc_placeholder('', slots)
        result = render_contents('# Goals\n\n' + next(iter(slots)), slots, [(1, 'Goals'), (2, 'Goals')], 'Goals')
        self.assertIn('(#argus-heading-goals)', result)
        self.assertIn('(#argus-heading-goals-1)', result)
        self.assertNotIn('goals-2', result)

    def test_inline_formatting_uses_visible_text(self):
        self.assertEqual(collect_headings('<h2><strong>General</strong> <code>description</code></h2>'), [(2, 'General description')])
        self.assertIn('[General description](#argus-heading-general-description)', self.render('<h2><strong>General</strong> <code>description</code></h2>'))

    def test_unicode_punctuation_and_entities(self):
        result = unquote(self.render('<h2>Διαγνωστικά &amp; Timing!</h2>'))
        self.assertIn('#argus-heading-διαγνωστικά--timing', result)
        self.assertIn(r'Διαγνωστικά &amp; Timing\!', result)
        self.assertEqual(heading_slug('!!!'), 'section')

    def test_code_examples_do_not_become_toc_entries(self):
        self.assertEqual(collect_headings('<pre><code>&lt;h2&gt;Example&lt;/h2&gt;</code></pre><h2>Real</h2>'), [(2, 'Real')])

    def test_invalid_levels_fall_back_to_defaults(self):
        result = self.render('<h2>Goals</h2>', '<ac:parameter ac:name="minLevel">banana</ac:parameter><ac:parameter ac:name="maxLevel">9</ac:parameter>')
        self.assertIn('[Goals]', result)

    def test_no_headings_leaves_no_placeholder(self):
        self.assertEqual(self.render('<p>Only prose.</p>'), 'Before\n\n\n\nAfter')

    def test_no_macro_does_not_add_contents(self):
        self.assertEqual(render_contents('Original body', {}, [(2, 'Goals')]), 'Original body')

    def test_multiple_tocs_have_independent_filters(self):
        slots = {}
        toc_placeholder('', slots)
        toc_placeholder('<ac:parameter ac:name="minLevel">3</ac:parameter>', slots)
        first, second = slots
        result = render_contents(first + '\nSEPARATOR\n' + second, slots, [(2, 'Goals'), (3, 'Manuals')])
        before, after = result.split('SEPARATOR')
        self.assertIn('[Goals]', before)
        self.assertNotIn('[Goals]', after)
        self.assertIn('[Manuals]', after)

    def test_skipped_heading_levels_form_a_valid_nested_list(self):
        result = self.render('<h2>A</h2><h4>B</h4><h3>C</h3><h2>D</h2>')
        self.assertIn('\n  - [B]', result)
        self.assertIn('\n  - [C]', result)
        self.assertIn('\n- [D]', result)

    def test_heading_label_escapes_markdown(self):
        result = self.render('<h2>A [B] *C* &lt;D&gt;</h2>')
        self.assertIn(r'A \[B\] \*C\* \<D\>', result)

    def test_contents_inside_quote_keeps_each_item_quoted(self):
        slots = {}
        toc_placeholder('', slots)
        result = render_contents('> ' + next(iter(slots)), slots, [(2, 'Goals'), (2, 'Resources')])
        self.assertEqual(result, '> - [Goals](#argus-heading-goals)\n> - [Resources](#argus-heading-resources)')


if __name__ == '__main__':
    unittest.main()
