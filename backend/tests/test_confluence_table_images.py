"""Regression cases for native Confluence images inside table cells."""
import re

from app.services.confluence_import import storage_to_markdown


def test_two_table_figures_are_images_not_alt_text():
    body = storage_to_markdown(
        '<table><tbody><tr><td><ac:image><ri:attachment ri:filename="Fig1.png"/></ac:image>'
        '<p><em>Fig.1 - Main tab</em></p></td>'
        '<td><ac:image><ri:attachment ri:filename="Fig2.png"/></ac:image>'
        '<p><em>Fig.2 - Sampling clock</em></p></td></tr></tbody></table>',
        {'Fig1.png': '/v1/attachments/figure-one', 'Fig2.png': '/v1/attachments/figure-two'},
    )
    assert '![Fig1.png](/v1/attachments/figure-one)' in body
    assert '![Fig2.png](/v1/attachments/figure-two)' in body
    assert 'Fig.1 - Main tab' in body and 'Fig.2 - Sampling clock' in body
    image_lines = [line for line in body.splitlines() if '![Fig' in line]
    assert image_lines and all(line.startswith('|') for line in image_lines)


def test_source_paragraph_wrapped_table_image_is_kept():
    body = storage_to_markdown('<table><tr><td><p><ac:image><ri:attachment ri:filename="ADC.png"/></ac:image></p></td></tr></table>',
                               {'ADC.png': '/v1/attachments/adc-image'})
    assert '![ADC.png](/v1/attachments/adc-image)' in body


def test_raw_html_images_in_table_body_and_header_are_kept():
    body = storage_to_markdown('<table><thead><tr><th><img src="/v1/attachments/header" alt="Header"/></th></tr></thead>'
                               '<tbody><tr><td><p><img src="/v1/attachments/body" alt="Body"/></p></td></tr></tbody></table>')
    assert '![Header](/v1/attachments/header)' in body
    assert '![Body](/v1/attachments/body)' in body


def test_external_confluence_image_inside_table_keeps_url():
    body = storage_to_markdown('<table><tr><td><ac:image><ri:url ri:value="https://example.invalid/diagram.png"/></ac:image></td></tr></table>')
    assert '![](https://example.invalid/diagram.png)' in body


def test_missing_download_does_not_invent_an_attachment_link():
    body = storage_to_markdown('<table><tr><td><ac:image><ri:attachment ri:filename="Missing.png"/></ac:image></td></tr></table>', {})
    assert 'Missing.png' in body
    assert not re.search(r'!\[[^\]]*\]\(/v1/attachments/', body)


def test_ordinary_table_values_and_outside_image_are_preserved():
    body = storage_to_markdown('<table><tr><th>Setting</th><th>Value</th></tr><tr><td>Coupling</td><td>DC</td></tr></table>'
                               '<ac:image><ri:attachment ri:filename="Outside.png"/></ac:image>',
                               {'Outside.png': '/v1/attachments/outside'})
    assert 'Coupling' in body and 'DC' in body
    assert '![Outside.png](/v1/attachments/outside)' in body
