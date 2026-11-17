"""Offline layout/conversion guards; no database or source account required."""
from html.parser import HTMLParser
import re
import unittest
from app.services.confluence_tables import protect_complex_tables, restore_complex_tables, table_contents_slots


class TableTests(unittest.TestCase):
    def convert(self, source, panels=None, contents=None):
        protected, slots = protect_complex_tables(source, panels, contents)
        return restore_complex_tables(protected, slots), slots

    def test_simple_parameter_table_stays_markdown_candidate(self):
        source = '<table><tr><th>Setting</th><th>Value</th></tr><tr><td>Range</td><td>50 V</td></tr></table>'
        protected, slots = protect_complex_tables(source)
        self.assertEqual(protected, source)
        self.assertEqual(slots, {})

    def test_simple_image_table_keeps_previous_conversion_path(self):
        source = '<table><tr><td><p><img src="/v1/attachments/image" alt="Figure 1"/></p><p>Caption</p></td></tr></table>'
        self.assertEqual(protect_complex_tables(source), (source, {}))

    def test_nested_grid_and_merged_cells_are_preserved(self):
        source = '<table><tr><td colspan="2"><table><tr><td>01</td><td>02</td></tr><tr><td colspan="2">Available</td></tr></table></td></tr></table>'
        result, slots = self.convert(source)
        self.assertEqual(len(slots), 1)
        self.assertEqual(result.count('<table '), 2)
        self.assertEqual(result.count('colspan="2"'), 2)
        self.assertIn('argus-confluence-nested-table', result)
        self.assertNotIn('ARGUSRICHTABLE', result)

    def test_24_port_structure_is_not_flattened(self):
        header = ''.join(f'<td>{port:02d}</td>' for port in range(1,25))
        tags = ''.join(f'<td><span style="background-color:#fff0b3">{tag} tag</span></td>' for tag in ['B','A','B','A','B','A'])
        nested = '<table><tr>'+header+'</tr><tr>'+tags+'<td colspan="4" style="background-color:rgb(75,206,151)">Available 4 ports</td><td colspan="14" style="background-color:#f87168">Not connected ports - Not available</td></tr></table>'
        result, _ = self.convert('<table><tr><th colspan="2" style="background-color:#8d929b;color:white">Rack R_RUF_02</th></tr><tr><td colspan="2">'+nested+'</td></tr><tr><td><p>RF Driver</p><p>Connected to</p><p>FANOUT Port: 01</p></td><td>FANOUT Port: 02</td></tr></table>')
        self.assertEqual(result.count('<table '), 2)
        self.assertIn('colspan="14"', result)
        self.assertIn('colspan="4"', result)
        self.assertIn('argus-rich-bg-4bce97', result)
        self.assertIn('argus-rich-bg-8d929b', result)
        self.assertIn('argus-rich-fg-ffffff', result)
        self.assertIn('argus-rich-bg-fff0b3', result)
        self.assertEqual(result.count('<p '), 3)
        for port in range(1,25):
            self.assertRegex(result, '>'+f'{port:02d}'+'</td>')

    def test_source_colours_and_alignment_become_bounded_tokens(self):
        result, _ = self.convert('<table><tr><td data-highlight-colour="#abc" style="color:rgb(1,2,3);text-align:center;vertical-align:middle">Text</td></tr></table>')
        for token in ['bg-aabbcc','fg-010203','align-center','valign-middle']:
            self.assertIn('argus-rich-'+token, result)
        self.assertNotIn('style=', result)
        self.assertNotIn('data-highlight', result)

    def test_column_widths_and_rowspan_are_preserved(self):
        result, _ = self.convert('<table data-table-width="1072"><colgroup><col style="width:25%"/><col width="96"/></colgroup><tr><td rowspan="2">A</td><td>B</td></tr><tr><td>C</td></tr></table>')
        for token in ['w-1072px','w-25pct','w-96px']:
            self.assertIn('argus-rich-'+token, result)
        self.assertIn('rowspan="2"', result)
        self.assertIn('<colgroup ', result)

    def test_unrelated_prose_is_byte_for_byte_unchanged(self):
        before = '<h1>Original &amp; title</h1>\n<p>Before</p>\n'
        after = '\n<pre>&lt;code&gt;</pre>\n'
        protected, slots = protect_complex_tables(before+'<table><tr><td colspan="2">Data</td></tr></table>'+after)
        self.assertTrue(protected.startswith(before))
        self.assertTrue(protected.endswith(after))
        self.assertEqual(len(slots), 1)

    def test_code_table_is_left_untouched(self):
        source = '<pre><code><table><tr><td colspan="2">example</td></tr></table></code></pre>'
        self.assertEqual(protect_complex_tables(source), (source, {}))

    def test_unknown_css_cannot_become_executable_style(self):
        result, _ = self.convert('<table><tr><td colspan="2" onclick="bad()" style="background-image:url(javascript:bad);width:999999px;position:fixed;color:expression(bad)">Keep</td></tr></table>')
        self.assertIn('Keep', result)
        for forbidden in ['onclick','javascript','expression','position','999999','style=']:
            self.assertNotIn(forbidden, result)

    def test_active_elements_and_unsafe_urls_are_removed(self):
        result, _ = self.convert('<table><tr><td colspan="2"><script>evil()</script><iframe src="x">hidden</iframe><a href="java&#115;cript:bad()">Label</a><img src="data:text/html,bad" onerror="bad"/><a href="/attachments/file">Manual</a><img src="/v1/attachments/image" alt="ADC"/></td></tr></table>')
        self.assertNotIn('evil()', result)
        self.assertNotIn('hidden', result)
        self.assertNotIn('javascript', result)
        self.assertNotIn('onerror', result)
        self.assertNotIn('data:text', result)
        self.assertIn('href="/attachments/file"', result)
        self.assertIn('src="/v1/attachments/image"', result)
        self.assertIn('>Label</a>', result)

    def test_literal_html_text_stays_escaped_after_restore(self):
        protected, slots = protect_complex_tables('<table><tr><td colspan="2">&lt;script&gt;not code&lt;/script&gt; &amp; text</td></tr></table>')
        result = restore_complex_tables(protected, slots)
        self.assertIn('&lt;script&gt;not code&lt;/script&gt;', result)
        self.assertNotIn('<script>', result)

    def test_invalid_spans_are_not_emitted(self):
        result, _ = self.convert('<table style="width:90%"><tr><td colspan="999999" rowspan="-2">Value</td></tr></table>')
        self.assertNotIn('colspan=', result)
        self.assertNotIn('rowspan=', result)

    def test_panels_inside_cells_keep_background_and_body(self):
        opening = 'ARGUSPANEL'+'a'*32+'OPEN'
        closing = 'ARGUSPANEL'+'a'*32+'CLOSE'
        result, _ = self.convert('<table><tr><td><p>'+opening+'</p><p><strong>Important:</strong> B tag</p><p>'+closing+'</p></td></tr></table>', {opening:'<div class="argus-confluence-panel argus-confluence-panel-bg-fffae6">', closing:'</div>'})
        self.assertIn('<div class="argus-confluence-panel argus-confluence-panel-bg-fffae6">', result)
        self.assertIn('Important:', result)
        self.assertNotIn('ARGUSPANEL', result)

    def test_styled_status_row_still_removes_only_prompt(self):
        result, _ = self.convert('<table><tr><th style="background-color:#abcdef">Document status</th><td>SET a STATUS <strong>IN PROGRESS</strong></td></tr><tr><td>Instruction</td><td>SET a STATUS unchanged</td></tr></table>')
        self.assertIn('>IN PROGRESS</strong>', result)
        self.assertEqual(result.count('SET a STATUS'), 1)
        self.assertIn('SET a STATUS unchanged', result)

    def test_uppercase_and_spaced_closing_tag_offsets(self):
        result, _ = self.convert('<TABLE><TR><TD COLSPAN="2">Data</TD></TR></TABLE >After')
        self.assertTrue(result.endswith('After'))
        self.assertNotIn('</TABLE', result)
        self.assertNotIn(' >After', result)

    def test_multiple_outer_tables_have_independent_slots(self):
        protected, slots = protect_complex_tables('<table><tr><td colspan="2">First</td></tr></table><p>Between</p><table><tr><td rowspan="2">Second</td></tr></table>')
        self.assertEqual(len(slots), 2)
        restored = restore_complex_tables(protected, slots)
        self.assertLess(restored.index('First'), restored.index('Between'))
        self.assertLess(restored.index('Between'), restored.index('Second'))

    def test_contents_inside_table_remain_html_links(self):
        slots = table_contents_slots('<h1>Title</h1>', {'MARKER': {}}, [(1,'Title'),(2,'Resources'),(3,'Manuals'),(2,'Resources')], 'Title')
        result, _ = self.convert('<table><tr><td colspan="2"><p>MARKER</p></td></tr></table>', contents=slots)
        self.assertIn('href="#argus-heading-resources"', result)
        self.assertIn('href="#argus-heading-resources-1"', result)
        self.assertIn('href="#argus-heading-manuals"', result)
        self.assertNotIn('MARKER', result)

    def test_inserted_title_reserves_duplicate_heading_id(self):
        slots = table_contents_slots('<p>Intro</p><h1>Title</h1>', {'MARKER': {}}, [(1,'Title')], 'Title')
        self.assertIn('href="#argus-heading-title-1"', slots['MARKER'])


class SourceNoteTests(unittest.TestCase):
    def render(self, body, parameters=''):
        from app.services.confluence_tables import source_note_panel
        from app.services.confluence_visuals import render_panel_wrappers
        slots = {}
        return render_panel_wrappers(source_note_panel(body, '<ac:structured-macro ac:name="note">'+parameters+'</ac:structured-macro>', slots), slots)

    def test_source_note_is_yellow_without_added_title(self):
        result = self.render('<p><strong>Important</strong>: Use the B tag.</p>')
        self.assertIn('argus-confluence-panel-bg-fffae6', result)
        self.assertIn('<p>⚠️ <strong>Important</strong>: Use the B tag.</p>', result)
        self.assertNotIn('📝', result)
        self.assertNotIn('>Note<', result)

    def test_explicit_note_title_and_icon_option_are_retained(self):
        result = self.render('<p>Body.</p>', '<ac:parameter ac:name="title">Read first</ac:parameter><ac:parameter ac:name="icon">false</ac:parameter>')
        self.assertIn('<strong>Read first</strong>', result)
        self.assertNotIn('⚠️', result)

    def test_explicit_note_colour_is_not_overridden(self):
        result = self.render('<p>Body.</p>', '<ac:parameter ac:name="bgColor">#abcdef</ac:parameter>')
        self.assertIn('argus-confluence-panel-bg-abcdef', result)

    def test_note_body_without_paragraph_is_not_discarded(self):
        result = self.render('<ul><li>Keep this.</li></ul>')
        self.assertIn('<ul><li>Keep this.</li></ul>', result)
        self.assertIn('⚠️', result)
