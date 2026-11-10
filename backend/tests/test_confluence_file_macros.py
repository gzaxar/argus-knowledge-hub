"""File-viewer conversion and bounded repair; no DB or live site required."""
import unittest

from app.services.confluence_file_macros import render_file_macro, replace_file_viewer_placeholders


def macro(filename="cx2000_en.pdf", name="view-file"):
    return f'<ac:structured-macro ac:name="{name}"><ac:parameter ac:name="name"><ri:attachment ri:filename="{filename}" /></ac:parameter></ac:structured-macro>'


class FileMacroTests(unittest.TestCase):
    def test_downloaded_pdf_is_linked(self):
        html = render_file_macro(macro(), "view-file", {"cx2000_en.pdf": "/v1/attachments/real-uid"})
        self.assertIn('<a href="/v1/attachments/real-uid">cx2000_en.pdf</a>', html)
        self.assertNotIn("see the original", html)

    def test_single_quoted_attachment_attribute(self):
        html = render_file_macro(macro().replace('ri:filename="cx2000_en.pdf"', "ri:filename='cx2000_en.pdf'"), "view-file", {"cx2000_en.pdf": "/v1/attachments/uid"})
        self.assertIn('href="/v1/attachments/uid"', html)

    def test_entities_in_filename(self):
        html = render_file_macro(macro("A &amp; B.pdf"), "view-file", {"A & B.pdf": "/v1/attachments/uid"})
        self.assertIn('href="/v1/attachments/uid"', html)
        self.assertIn("A &amp; B.pdf", html)

    def test_url_encoded_filename_matches_existing_file(self):
        html = render_file_macro(macro("A%20B.pdf"), "view-file", {"A B.pdf": "/v1/attachments/uid"})
        self.assertIn('>A B.pdf</a>', html)

    def test_literal_percent_filename_wins_over_decoded_name(self):
        html = render_file_macro(macro("A%20B.pdf"), "view-file", {"A%20B.pdf": "/v1/attachments/exact", "A B.pdf": "/v1/attachments/other"})
        self.assertIn('href="/v1/attachments/exact"', html)

    def test_missing_download_remains_visible_without_invented_link(self):
        html = render_file_macro(macro(), "view-file", {})
        self.assertIn("Attachment not imported: cx2000_en.pdf", html)
        self.assertNotIn("href=", html)

    def test_other_page_file_is_not_confused_with_same_filename(self):
        source = macro().replace('ri:filename="cx2000_en.pdf" />', 'ri:filename="cx2000_en.pdf"><ri:page ri:content-title="Other page" /></ri:attachment>')
        html = render_file_macro(source, "view-file", {"cx2000_en.pdf": "/v1/attachments/wrong-file"})
        self.assertIn("another Confluence page", html)
        self.assertNotIn("href=", html)

    def test_markup_in_filename_is_escaped(self):
        html = render_file_macro(macro("&lt;script&gt;.pdf"), "view-file", {"<script>.pdf": "/v1/attachments/uid"})
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;.pdf", html)

    def test_missing_reference_is_reported(self):
        self.assertIn("no attachment reference", render_file_macro('<ac:structured-macro ac:name="view-file" />', "view-file", {}))

    def test_duplicate_reference_is_only_rendered_once(self):
        self.assertEqual(render_file_macro(macro() + macro(), "view-file", {"cx2000_en.pdf": "/v1/attachments/uid"}).count("<a "), 1)

    def test_paired_attachment_is_supported(self):
        source = macro().replace('ri:filename="cx2000_en.pdf" />', 'ri:filename="cx2000_en.pdf"></ri:attachment>')
        self.assertIn("href=", render_file_macro(source, "view-file", {"cx2000_en.pdf": "/v1/attachments/uid"}))


class PlaceholderRepairTests(unittest.TestCase):
    def test_only_placeholder_changes(self):
        original = "User-edited introduction\n\n*[view-file — see the original page]*\n\nBECKHOFF CX20xx Manual\n\n*[contentbylabel — see the original page]*"
        link = "[cx2000_en.pdf](/v1/attachments/uid)"
        changed = replace_file_viewer_placeholders(original, [("view-file", link)])
        self.assertEqual(changed, original.replace("*[view-file — see the original page]*", link))

    def test_markdown_escaped_marker(self):
        original = r"*\[view-file — see the original page\]*"
        self.assertEqual(replace_file_viewer_placeholders(original, [("view-file", "LINK")]), "LINK")

    def test_two_macros_keep_source_order(self):
        original = "[view-file — see the original page]\n[view-file — see the original page]"
        self.assertEqual(replace_file_viewer_placeholders(original, [("view-file", "ONE"), ("view-file", "TWO")]), "ONE\nTWO")

    def test_count_mismatch_refuses_to_guess(self):
        with self.assertRaisesRegex(ValueError, "Cannot match"):
            replace_file_viewer_placeholders("No marker remains", [("view-file", "LINK")])

    def test_multiple_types_are_matched_separately(self):
        original = "[viewpdf — see the original page]\n[view-file — see the original page]"
        self.assertEqual(replace_file_viewer_placeholders(original, [("view-file", "FILE"), ("viewpdf", "PDF")]), "PDF\nFILE")


if __name__ == "__main__":
    unittest.main()
