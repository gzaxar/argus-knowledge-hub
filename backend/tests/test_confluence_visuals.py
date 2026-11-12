import unittest
from app.services.confluence_visuals import panel_placeholder, render_emoticons, render_panel_wrappers


class VisualTests(unittest.TestCase):
    def test_source_emoji_fallback(self):
        self.assertEqual(render_emoticons('<h2><ac:emoticon ac:emoji-fallback="📘"/> Procedure</h2>'), '<h2>📘 Procedure</h2>')

    def test_codepoint_identifier(self):
        self.assertEqual(render_emoticons('<ac:emoticon ac:emoji-id="1f4d8"/>'), '📘')

    def test_named_emojis(self):
        self.assertEqual(render_emoticons('<ac:emoticon ac:emoji-shortname=":compass:"/>'), '🧭')
        self.assertEqual(render_emoticons('<ac:emoticon ac:name="clipboard"/>'), '📋')

    def test_invalid_icon_is_explicit_and_safe(self):
        result = render_emoticons('<ac:emoticon ac:name="unrecognised" ac:emoji-fallback="&lt;script&gt;" ac:emoji-id="110000"/>')
        self.assertEqual(result, '[Confluence icon unavailable]')

    def test_code_example_not_converted(self):
        body = '<ac:plain-text-body><![CDATA[<ac:emoticon ac:name="clipboard"/>]]></ac:plain-text-body>'
        self.assertEqual(render_emoticons(body), body)

    def test_panel_source_background_is_retained(self):
        slots = {}
        token = panel_placeholder('panel', '<p><strong>Timing ADC</strong> Software GUI</p>', '<ac:parameter ac:name="bgColor">#E6FCFF</ac:parameter>', slots)
        result = render_panel_wrappers(token, slots)
        self.assertIn('argus-confluence-panel-bg-e6fcff', result)
        self.assertIn('Timing ADC', result)
        self.assertNotIn('ARGUSPANEL', result)

    def test_info_default_and_custom_title(self):
        slots = {}
        token = panel_placeholder('info', '<p>Read this.</p>', '<ac:parameter ac:name="title">Read first</ac:parameter>', slots)
        result = render_panel_wrappers(token, slots)
        self.assertIn('ℹ️ Read first', result)
        self.assertIn('argus-confluence-panel-bg-deebff', result)

    def test_invalid_colour_cannot_inject_css(self):
        slots = {}
        panel_placeholder('panel', '<p>Text</p>', '<ac:parameter ac:name="bgColor">url(javascript:bad)</ac:parameter>', slots)
        self.assertFalse(any('javascript' in value for value in slots.values()))

    def test_border_colour_is_validated(self):
        slots = {}
        panel_placeholder('panel', '<p>Text</p>', '<ac:parameter ac:name="borderColor">#abc</ac:parameter>', slots)
        self.assertTrue(any('border-aabbcc' in value for value in slots.values()))

    def test_nested_panel_tokens_restored(self):
        slots = {}
        inside = panel_placeholder('note', '<p>Inner</p>', '', slots)
        outside = panel_placeholder('panel', inside, '', slots)
        result = render_panel_wrappers(outside, slots)
        self.assertEqual(result.count('<div class='), 2)
        self.assertNotIn('ARGUSPANEL', result)

    def test_panel_in_table_does_not_break_markdown_table(self):
        slots = {}
        panel_placeholder('panel', '<p>Text</p>', '', slots)
        opening, closing = slots
        result = render_panel_wrappers('| '+opening+'Text'+closing+' |', slots)
        self.assertEqual(result, '| Text |')


if __name__ == '__main__':
    unittest.main()
