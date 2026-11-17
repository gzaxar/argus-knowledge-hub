"""Run with the real native importer and its pinned markdownify dependency."""
from html.parser import HTMLParser

from app.services.confluence_import import storage_to_markdown


def test_complex_native_table_preserves_grid_panels_and_downloaded_image():
    source = ('<table><tr><th colspan="2" style="background-color:#8d929b;color:#ffffff">Rack R_RUF_02</th></tr>'
              '<tr><td colspan="2"><table><tr><td>01</td><td>02</td></tr>'
              '<tr><td colspan="2" data-highlight-colour="#4bce97">Available</td></tr></table></td></tr>'
              '<tr><td><p>RF Driver</p><p>Connected to</p><p>FANOUT Port: 01</p>'
              '<ac:structured-macro ac:name="warning"><ac:parameter ac:name="title">Important</ac:parameter>'
              '<ac:rich-text-body><p>Use the B tag.</p></ac:rich-text-body></ac:structured-macro></td>'
              '<td><ac:image><ri:attachment ri:filename="ADC.png"/></ac:image></td></tr></table>')
    result = storage_to_markdown(source, {'ADC.png':'/v1/attachments/adc-image'})
    assert result.count('<table ') == 2
    assert 'colspan="2"' in result
    assert 'argus-rich-bg-8d929b' in result
    assert 'argus-rich-bg-4bce97' in result
    assert 'argus-confluence-panel-bg-fffae6' in result
    assert 'src="/v1/attachments/adc-image"' in result
    assert 'RF Driver</p>' in result
    assert 'Connected to</p>' in result
    assert 'ARGUSPANEL' not in result and 'ARGUSRICHTABLE' not in result


def test_plain_parameter_and_picture_tables_still_use_markdown():
    result = storage_to_markdown('<table><tr><td>Parameter</td><td>10 Hz</td></tr></table>'
                                '<table><tr><td><ac:image><ri:attachment ri:filename="ADC.png"/></ac:image></td></tr></table>',
                                {'ADC.png':'/v1/attachments/adc-image'})
    assert '| Parameter | 10 Hz |' in result
    assert '![ADC.png](/v1/attachments/adc-image)' in result
    assert 'argus-confluence-rich-table' not in result


def test_contents_in_and_outside_complex_table_keep_target_links():
    result = storage_to_markdown('<ac:structured-macro ac:name="toc"/><h2>Resources</h2>'
        '<table><tr><td colspan="2"><ac:structured-macro ac:name="toc"/></td></tr></table>', title='Source title')
    assert '#argus-heading-resources' in result
    assert 'href="#argus-heading-resources"' in result
    assert 'ARGUSCONTENTSMARKER' not in result


def test_styled_metadata_keeps_owner_resolution_and_status_cleanup():
    source = ('<table><tr><th style="background-color:#deebff">Document owner</th>'
              '<td><ac:link><ri:user ri:account-id="one"/></ac:link> <ac:link><ri:user ri:account-id="two"/></ac:link></td></tr>'
              '<tr><th>Document status</th><td>SET a STATUS <ac:structured-macro ac:name="status">'
              '<ac:parameter ac:name="title">In progress</ac:parameter></ac:structured-macro></td></tr></table>')
    result = storage_to_markdown(source, user_names={('accountId','one'):'Owner One',('accountId','two'):'Owner Two'})
    # Rich tables retain a separate span for each source user mention.
    # Check visible text, including the actual separator, rather than HTML adjacency.
    parts = []

    class VisibleText(HTMLParser):
        def handle_data(self, text):
            parts.append(text)

    parser = VisibleText(convert_charrefs=True)
    parser.feed(result)
    parser.close()
    visible = ''.join(parts)
    assert 'Owner One - Owner Two' in visible
    assert visible.count('Owner One') == 1
    assert visible.count('Owner Two') == 1
    assert 'In progress' in visible
    assert 'SET a STATUS' not in visible


def test_source_note_inside_table_is_yellow_without_an_invented_note_title():
    source = ('<table><tr><td colspan="2"><ac:structured-macro ac:name="note">'
              '<ac:rich-text-body><p><strong>Important</strong>: Use the B tag.</p>'
              '</ac:rich-text-body></ac:structured-macro></td></tr></table>')
    result = storage_to_markdown(source)
    assert 'argus-confluence-panel-bg-fffae6' in result
    assert '⚠️' in result
    assert 'Important' in result
    assert '>Note<' not in result
    assert '📝' not in result
