"""Run in ARGUS's backend test environment with its markdownify dependency."""
from app.services.confluence_import import storage_to_markdown
from app.services.confluence_presentation import prepare_presentation


def test_native_toc_position_links_and_nested_sections():
    body = storage_to_markdown(
        '<table><tr><td>Document owner</td><td>Owner</td></tr></table>'
        '<ac:structured-macro ac:name="toc"><ac:parameter ac:name="maxLevel">3</ac:parameter></ac:structured-macro>'
        '<h2>Goals</h2><p>Goal text.</p><h2>Resources</h2><h3>Manuals</h3><h4>Detail</h4>'
    )
    assert body.index('Document owner') < body.index('[Goals](#argus-heading-goals)') < body.index('## Goals')
    assert '- [Resources](#argus-heading-resources)\n  - [Manuals](#argus-heading-manuals)' in body
    assert '[Detail]' not in body and '#### Detail' in body
    assert 'ARGUSCONTENTSMARKER' not in body and 'ac:' not in body


def test_native_self_closing_toc_inside_panel_preserves_following_content():
    body = storage_to_markdown('<ac:structured-macro ac:name="info"><ac:rich-text-body>'
                               '<ac:structured-macro ac:name="toc" /><p>Keep this paragraph.</p>'
                               '</ac:rich-text-body></ac:structured-macro><h2>Goals</h2>')
    assert '[Goals](#argus-heading-goals)' in body
    assert 'Keep this paragraph.' in body
    assert '## Goals' in body


def test_native_toc_with_no_headings_has_no_marker():
    assert storage_to_markdown('<p>Before</p><ac:structured-macro ac:name="toc" /><p>After</p>') == 'Before\n\nAfter'


def test_native_toc_keeps_attachment_urls_and_images():
    body = storage_to_markdown('<ac:structured-macro ac:name="toc" /><h2>Resources</h2>'
                               '<ac:image><ri:attachment ri:filename="Diagram.png" /></ac:image>'
                               '<ac:link><ri:attachment ri:filename="K2 UM.pdf" /></ac:link>',
                               {'Diagram.png': '/v1/attachments/image-uid', 'K2 UM.pdf': '/v1/attachments/pdf-uid'})
    assert '[Resources](#argus-heading-resources)' in body
    assert '![Diagram.png](/v1/attachments/image-uid)' in body
    assert '/v1/attachments/pdf-uid' in body


def test_native_toc_accounts_for_prepended_page_title():
    storage = '<ac:structured-macro ac:name="toc" /><h2>Goals</h2>'
    converted = storage_to_markdown(storage, title='Goals')
    body, _ = prepare_presentation('Goals', converted, {}, storage)
    assert body.startswith('# Goals\n')
    assert '[Goals](#argus-heading-goals-1)' in body


def test_native_page_without_toc_does_not_gain_one():
    assert storage_to_markdown('<h2>Goals</h2><p>Goal text.</p>') == '## Goals\n\nGoal text.'
