"""Summaries and literal source headings without application/database dependencies."""
import unittest

from app.services.confluence_presentation import prepare_presentation, source_summary, title_heading


class PresentationTests(unittest.TestCase):
    def test_summary_extracts_the_actual_modulator_introduction(self):
        text = "The modulators are equipped with a BECKHOFF CX20X0 embedded computer with two RJ45 sockets (see attached manual):"
        self.assertEqual(source_summary(f"<p>{text}</p><h2>Instructions</h2><p>Connect the X000 RJ45 socket to the switch.</p>"), text)

    def test_summary_preserves_inline_identifiers(self):
        self.assertEqual(source_summary("<p>The controller uses <code>CX20X0</code> hardware with <strong>two RJ45 sockets</strong>.</p>"), "The controller uses CX20X0 hardware with two RJ45 sockets.")

    def test_summary_ignores_metadata_tables_and_macro_panels(self):
        storage = '<table><tr><td><p>Metadata from an owner table should not become a summary.</p></td></tr></table><ac:structured-macro ac:name="note"><ac:rich-text-body><p>A panel that should not become the document summary.</p></ac:rich-text-body></ac:structured-macro><p>This page describes the RF sources and their distribution systems.</p>'
        self.assertEqual(source_summary(storage), "This page describes the RF sources and their distribution systems.")

    def test_summary_omits_credentials_and_steps(self):
        storage = '<p>Enter the authentication credentials 12345678 when the screen requests them.</p><ol><li><p>This is a sufficiently long numbered instruction that must be excluded.</p></li></ol><p>This overview describes the Ethernet connection to the control system.</p>'
        self.assertEqual(source_summary(storage), "This overview describes the Ethernet connection to the control system.")

    def test_summary_ignores_code_blocks(self):
        self.assertEqual(source_summary('<pre><code>A long executable command must not be used as a descriptive summary.</code></pre>'), "")

    def test_no_summary_is_invented_when_only_headings_exist(self):
        self.assertEqual(source_summary('<h1>RF system</h1><h2>Resources</h2>'), "")

    def test_summary_length_is_bounded_at_a_word_boundary(self):
        text = "This document describes " + "equipment " * 100
        result = source_summary(f"<p>{text}</p>")
        self.assertLessEqual(len(result), 480)
        self.assertTrue(result.endswith("…"))

    def test_existing_summary_is_preserved_and_input_is_not_mutated(self):
        attrs = {"argus_summary": "My reviewed summary.", "local": "keep"}
        body, result = prepare_presentation("Source title", "Existing text", attrs, "<p>A sufficiently long source introduction is available here.</p>")
        self.assertEqual(result["argus_summary"], "My reviewed summary.")
        self.assertEqual(attrs, {"argus_summary": "My reviewed summary.", "local": "keep"})
        self.assertEqual(body, "# Source title\n\nExisting text")

    def test_missing_summary_uses_the_argus_summary_field(self):
        _, attrs = prepare_presentation("Title", "Body", {"argus_source_id": "123"}, "<p>This overview describes the RF distribution and its equipment.</p>")
        self.assertEqual(attrs["argus_source_id"], "123")
        self.assertEqual(attrs["argus_summary"], "This overview describes the RF distribution and its equipment.")

    def test_exact_title_is_added_above_existing_body(self):
        self.assertEqual(title_heading("How-to connect the modulator to the network", "Introduction\n\n## Instructions"), "# How-to connect the modulator to the network\n\nIntroduction\n\n## Instructions")

    def test_identical_heading_is_not_duplicated(self):
        body = "# WP02 - RF sources & RF distribution\n\nExisting text"
        self.assertEqual(title_heading("WP02 - RF sources & RF distribution", body), body)

    def test_literal_markdown_characters_are_escaped_and_idempotent(self):
        title = "SIGMA_PHI [setup] #1"
        result = title_heading(title, "Body")
        self.assertEqual(result, r"# SIGMA\_PHI \[setup\] \#1" + "\n\nBody")
        self.assertEqual(title_heading(title, result), result)

    def test_different_body_heading_is_preserved(self):
        self.assertEqual(title_heading("Source title", "# Local section\n\nBody"), "# Source title\n\n# Local section\n\nBody")

    def test_existing_pdf_links_are_untouched(self):
        body = "Manual: [cx2000_en.pdf](/v1/attachments/file-uid)"
        self.assertEqual(title_heading("Source title", body), "# Source title\n\n" + body)

    def test_empty_or_multiline_source_title_is_refused(self):
        for title in ("", " ", "Title\nnext line"):
            with self.subTest(title=title), self.assertRaises(ValueError):
                title_heading(title, "Body")


if __name__ == "__main__":
    unittest.main()
