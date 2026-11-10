"""Document navigation survives a workspace bundle, including identifier collisions."""
from __future__ import annotations

import secrets
import uuid

from sqlalchemy import select

from app.bundle import core, registry
from app.db import SessionLocal
from app.models.document import Document
from app.models.document_navigation import DocumentFolder, DocumentPlacement
from app.models.workspace import Workspace
from tests.test_workspace_bundles import _apply, _drop, _rows


def test_navigation_round_trips_with_folders_parent_pages_and_explicit_root(tmp_path):
    tag = secrets.token_hex(4)
    source, other = f'nav-src-{tag}', f'nav-other-{tag}'
    preview = f'nav-preview-{tag}'
    targets = [f'nav-copy1-{tag}', f'nav-copy2-{tag}']
    folder_root = 'z-root-' + str(uuid.uuid4())
    folder_child = 'a-child-' + str(uuid.uuid4())
    doc_ids = {name: str(uuid.uuid4()) for name in ['wp', 'folder_doc', 'page_doc', 'root_doc']}
    db = SessionLocal()
    try:
        db.add_all([Workspace(id=source, name='Navigation source'), Workspace(id=other, name='Unrelated')])
        db.flush()
        db.add(DocumentFolder(uid=folder_root, workspace_id=source, name='Manuals'))
        db.flush()
        # Export sorts by UID: the child is deliberately before its parent.
        db.add(DocumentFolder(uid=folder_child, workspace_id=source, name='Power supplies', parent_uid=folder_root))
        db.add(DocumentFolder(uid=str(uuid.uuid4()), workspace_id=other, name='Not exported'))
        for name, uid in doc_ids.items():
            db.add(Document(uid=uid, workspace_id=source, code=f'{tag}-{name}', title=name))
        db.flush()
        db.add_all([
            DocumentPlacement(document_uid=doc_ids['folder_doc'], workspace_id=source, folder_uid=folder_child),
            DocumentPlacement(document_uid=doc_ids['page_doc'], workspace_id=source, parent_document_uid=doc_ids['wp']),
            DocumentPlacement(document_uid=doc_ids['root_doc'], workspace_id=source),
        ])
        db.commit()
        bundle_path = tmp_path / 'navigation-bundle'
        manifest = core.export(db, source, bundle_path, actor='test')
        assert manifest['families']['document_folders']['rows'] == 2
        assert manifest['families']['document_navigation_placements']['rows'] == 3
        assert [r['uid'] for r in _rows(bundle_path, 'document_folders')] == [folder_child, folder_root]
        assert {r['workspace_id'] for r in _rows(bundle_path, 'document_folders')} == {source}
        assert core.verify(core.read(bundle_path)) == []

        view = _apply(bundle_path, preview, tmp_path, dry_run=True)
        assert view['ok'], view['blockers']
        db.expire_all()
        assert db.get(Workspace, preview) is None
        db.rollback()

        copied_ids = []
        for target in targets:
            view = _apply(bundle_path, target, tmp_path)
            assert view['ok'], view['blockers']
            assert view['added']['document_folders'] == 2
            assert view['added']['document_navigation_placements'] == 3
            db.expire_all()
            folders = {f.name: f for f in db.scalars(select(DocumentFolder).where(DocumentFolder.workspace_id == target))}
            documents = {d.title: d for d in db.scalars(select(Document).where(Document.workspace_id == target))}
            placements = {p.document_uid: p for p in db.scalars(select(DocumentPlacement).where(DocumentPlacement.workspace_id == target))}
            assert set(folders) == {'Manuals', 'Power supplies'}
            assert set(documents) == set(doc_ids)
            assert folders['Power supplies'].parent_uid == folders['Manuals'].uid
            assert folders['Manuals'].parent_uid is None
            assert placements[documents['folder_doc'].uid].folder_uid == folders['Power supplies'].uid
            assert placements[documents['folder_doc'].uid].parent_document_uid is None
            assert placements[documents['page_doc'].uid].parent_document_uid == documents['wp'].uid
            assert placements[documents['page_doc'].uid].folder_uid is None
            root = placements[documents['root_doc'].uid]
            assert root.folder_uid is None and root.parent_document_uid is None
            # Absence of an override and an explicit root override are different states.
            assert documents['wp'].uid not in placements
            assert set(placements) == {documents[n].uid for n in ['folder_doc', 'page_doc', 'root_doc']}
            target_ids = {f.uid for f in folders.values()} | {d.uid for d in documents.values()}
            assert target_ids.isdisjoint({folder_root, folder_child} | set(doc_ids.values()))
            copied_ids.append(target_ids)
            db.rollback()
        assert copied_ids[0].isdisjoint(copied_ids[1])
        db.expire_all()
        assert db.get(DocumentFolder, folder_child).parent_uid == folder_root
        assert db.get(DocumentPlacement, doc_ids['page_doc']).parent_document_uid == doc_ids['wp']
    finally:
        db.rollback()
        db.close()
        _drop(*targets, preview, other, source)


def test_navigation_tables_are_carried_in_dependency_order():
    families = registry.build()
    by_name = {f.name: f for f in families}
    names = [f.name for f in families]
    assert by_name['document_folders'].model is DocumentFolder
    assert by_name['document_navigation_placements'].model is DocumentPlacement
    assert 'parent_uid' in by_name['document_folders'].deferred
    assert names.index('documents') < names.index('document_navigation_placements')
    assert names.index('document_folders') < names.index('document_navigation_placements')
    for table in ['document_folders', 'document_navigation_placements']:
        assert table not in registry.NOT_CARRIED and table not in registry.REBUILT
