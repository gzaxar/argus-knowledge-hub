"""Integration checks for the normal storage -> Markdown converter."""
from app.services.confluence_import import storage_to_markdown


def test_owner_and_status_table_preserves_visible_source_values():
    body = storage_to_markdown(
        '<table><tr><td><strong>Document owner</strong></td><td><ac:link><ri:user ri:account-id="owner-id"/></ac:link></td></tr>'
        '<tr><td><strong>Document status</strong></td><td><ac:structured-macro ac:name="status">'
        '<ac:parameter ac:name="title">IN PROGRESS</ac:parameter><ac:parameter ac:name="colour">Yellow</ac:parameter>'
        '</ac:structured-macro></td></tr></table>',
        user_names={('accountId', 'owner-id'): 'Giovanni Franzini'},
    )
    assert 'Document owner' in body and 'Giovanni Franzini' in body
    assert 'Document status' in body and 'IN PROGRESS' in body
    assert '[status — see the original page]' not in body
    assert 'ac:' not in body and 'ri:' not in body


def test_unresolved_owner_is_not_an_empty_cell():
    body = storage_to_markdown('<table><tr><td>Document owner</td><td><ri:user ri:userkey="unknown"/></td></tr></table>')
    assert 'Unresolved Confluence user' in body and 'unknown' in body


def test_toc_attachments_and_page_fields_work_together():
    body = storage_to_markdown('<p><ri:user ri:userkey="owner"/></p>'
                               '<ac:structured-macro ac:name="status"><ac:parameter ac:name="title">DRAFT</ac:parameter></ac:structured-macro>'
                               '<ac:structured-macro ac:name="toc"/><h2>Resources</h2>'
                               '<ac:link><ri:attachment ri:filename="K2 UM.pdf"/></ac:link>',
                               {'K2 UM.pdf': '/v1/attachments/pdf-uid'},
                               user_names={('key', 'owner'): 'Owner Name'})
    assert 'Owner Name' in body and 'DRAFT' in body
    assert '[Resources](#argus-heading-resources)' in body
    assert '/v1/attachments/pdf-uid' in body


def test_status_template_prompt_outside_badge_is_removed():
    body = storage_to_markdown('<table><tr><td><strong>Document status</strong></td><td>SET a STATUS '
                               '<ac:structured-macro ac:name="status"><ac:parameter ac:name="title">IN PROGRESS</ac:parameter></ac:structured-macro>'
                               '</td></tr></table>')
    assert '| **Document status** | IN PROGRESS |' in body


def test_status_template_prompt_in_separate_badge_is_removed():
    body = storage_to_markdown('<table><tr><td>Document status</td><td>'
                               '<ac:structured-macro ac:name="status"><ac:parameter ac:name="title">SET a STATUS</ac:parameter></ac:structured-macro> '
                               '<ac:structured-macro ac:name="status"><ac:parameter ac:name="title">IN PROGRESS</ac:parameter></ac:structured-macro>'
                               '</td></tr></table>')
    assert '| Document status | IN PROGRESS |' in body


def test_multiple_document_owners_have_dash_separator():
    body = storage_to_markdown('<table><tr><td><strong>Document owner</strong></td><td><p>'
                               '<ac:link><ri:user ri:account-id="a"/></ac:link> '
                               '<ac:link><ri:user ri:account-id="b"/></ac:link>'
                               '</p></td></tr></table>',
                               user_names={('accountId', 'a'): 'Giovanni Franzini', ('accountId', 'b'): 'Georgios Zachariadis'})
    assert '| **Document owner** | Giovanni Franzini - Georgios Zachariadis |' in body
