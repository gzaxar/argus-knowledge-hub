"""Integration checks: run in ARGUS's backend test environment with markdownify."""
from app.services.confluence_import import storage_to_markdown


def test_source_heading_icon_is_retained():
    result = storage_to_markdown('<h2><ac:emoticon ac:emoji-fallback="📘"/> Procedure</h2>')
    assert '## 📘 Procedure' in result


def test_source_panel_colour_icon_and_text_are_retained():
    result = storage_to_markdown(
        '<ac:structured-macro ac:name="panel"><ac:parameter ac:name="bgColor">#E6FCFF</ac:parameter>'
        '<ac:rich-text-body><p><ac:emoticon ac:emoji-shortname=":compass:"/> '
        '<strong>Timing ADC</strong> Software GUI</p></ac:rich-text-body></ac:structured-macro>')
    assert '<div class="argus-confluence-panel argus-confluence-panel-bg-e6fcff">' in result
    assert '🧭 **Timing ADC** Software GUI' in result
    assert '</div>' in result
    assert 'ARGUSPANEL' not in result


def test_panel_does_not_remove_figure_in_table():
    result = storage_to_markdown(
        '<ac:structured-macro ac:name="info"><ac:rich-text-body><p>Check first.</p>'
        '</ac:rich-text-body></ac:structured-macro><table><tr><td><ac:image>'
        '<ri:attachment ri:filename="Fig1.png"/></ac:image><p><em>Figure 1</em></p>'
        '</td></tr></table>', {'Fig1.png': '/v1/attachments/figure-one'})
    assert '![Fig1.png](/v1/attachments/figure-one)' in result
    assert 'Figure 1' in result
    assert 'argus-confluence-panel' in result
    assert 'ARGUSPANEL' not in result
