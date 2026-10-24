"""Workspace bundles (app/bundle, docs/workspace-bundle.md): the registry covers every table, the two demo workspaces
install from their directories and survive a round trip, and broken, unsafe or unauthorised imports are refused."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
import uuid
import zipfile
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect as sa_inspect, select

from app.auth import OidcIdentity, get_identity
from app.bundle import core, registry
from app.db import SessionLocal, engine as db_engine
from app.main import app
from app.models.user import User
from app.models.workspace import Workspace

DEMOS = Path(__file__).resolve().parents[1] / "demo_workspaces"
client = TestClient(app)


# --------------------------------------------------------------------------- helpers

def _drop(*workspaces: str) -> None:
    from app.ledger.audit import allow_purge
    db = SessionLocal()
    for ws in workspaces:
        w = db.get(Workspace, ws)
        if w is not None:
            allow_purge(db)
            db.delete(w)
            db.commit()
    db.close()


def _user(admin: bool) -> User:
    t = secrets.token_hex(4)
    db = SessionLocal()
    u = User(id=str(uuid.uuid4()), email=f"bundle-{t}@argus.test", name=f"Bundle {t}", is_admin=admin)
    db.add(u)
    db.commit()
    db.refresh(u)
    db.expunge(u)
    db.close()
    return u


@pytest.fixture()
def admin():
    u = _user(True)
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=u)
    yield u
    app.dependency_overrides.pop(get_identity, None)


def _copy(name: str, tmp: Path) -> Path:
    dest = tmp / name
    shutil.copytree(DEMOS / name, dest)
    return dest


def _reseal(root: Path) -> None:
    """After a test edits a bundle's records: the manifest's checksums made to match, so only the edit is wrong."""
    m = json.loads((root / "manifest.json").read_text())
    for meta in m["families"].values():
        p = root / meta["file"]
        if p.exists():
            data = p.read_bytes()
            meta["sha256"] = hashlib.sha256(data).hexdigest()
            meta["rows"] = sum(1 for line in data.splitlines() if line.strip())
    m["files"] = core.inventory(root)
    (root / "manifest.json").write_text(json.dumps(m, indent=1))


def _rows(root: Path, family: str) -> list[dict]:
    p = root / "records" / f"{family}.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def _write(root: Path, family: str, rows: list[dict]) -> None:
    (root / "records" / f"{family}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def _apply(root: Path, ws: str, tmp: Path, dry_run: bool = False, actor: str | None = None) -> dict:
    db = SessionLocal()
    try:
        rep = core.apply(db, core.read(root), workspace_id=ws, name=f"Test {ws}", actor=actor, dry_run=dry_run,
                         files_root=tmp / "files")
        if not dry_run and rep.view()["ok"]:
            db.commit()
        return rep.view()
    finally:
        db.close()


def _shape(db, ws: str) -> dict:
    """What a workspace holds, independent of identifiers: counts, file hashes, geometry, plans and placements."""
    from app.models.asset import Asset, Relation
    from app.models.attachment import Attachment
    from app.models.beam_model import BeamAssetBinding, BeamModelValue
    from app.models.indoor import FloorPlan, IndoorPlacement, PlaceLevel
    from app.models.issue import Issue
    from app.models.package import WorkspacePackage
    from app.models.spatial import SpatialFeature
    from app.models.document import Document

    def files(paths):
        out = []
        for p in paths:
            out.append(hashlib.sha256(Path(p).read_bytes()).hexdigest() if p and Path(p).is_file() else None)
        return sorted(out, key=str)

    assets = {a.uid: a for a in db.scalars(select(Asset).where(Asset.workspace_id == ws))}
    key = {u: a.key.rsplit("-", 1)[0] if a.key.endswith(f"-{ws}") else a.key for u, a in assets.items()}
    plans = list(db.scalars(select(FloorPlan).where(FloorPlan.workspace_id == ws)))
    placements = db.scalars(select(IndoorPlacement).where(IndoorPlacement.workspace_id == ws))
    return {
        "packages": sorted((p.package_id, p.version, p.checksum) for p in
                           db.scalars(select(WorkspacePackage).where(WorkspacePackage.workspace_id == ws))),
        "assets": Counter(a.type for a in assets.values()),
        "names": sorted(a.name for a in assets.values()),
        "relations": sorted((assets[r.from_asset_uid].name, r.relation_type, assets[r.to_asset_uid].name)
                            for r in db.scalars(select(Relation).where(Relation.workspace_id == ws))),
        "tickets": sorted(i.title for i in db.scalars(select(Issue).where(Issue.workspace_id == ws))),
        "documents": sorted(d.title for d in db.scalars(select(Document).where(Document.workspace_id == ws))),
        "attachments": files(a.storage_path for a in db.scalars(select(Attachment).where(Attachment.workspace_id == ws))),
        "geometry": sorted((assets[f.subject_uid].name, f.role, json.dumps(f.geometry, sort_keys=True))
                           for f in db.scalars(select(SpatialFeature).where(SpatialFeature.workspace_id == ws,
                                                                            SpatialFeature.state == "confirmed"))),
        "levels": sorted((assets[lv.place_uid].name, lv.name, lv.ordinal) for lv in
                         db.scalars(select(PlaceLevel).where(PlaceLevel.workspace_id == ws))),
        "plans": sorted((p.name, json.dumps(p.control_points, sort_keys=True)) for p in plans),
        "plan_files": files(p.storage_path for p in plans),
        "placements": sorted((assets[p.asset_uid].name, assets[p.place_uid].name if p.place_uid else None,
                              p.plan_x, p.plan_y) for p in placements),
        "beam_values": sorted((v.s, v.x, v.y) for v in db.scalars(select(BeamModelValue).where(BeamModelValue.workspace_id == ws))),
        "bindings": sorted((b.component_id, assets[b.asset_uid].name, b.status) for b in
                           db.scalars(select(BeamAssetBinding).where(BeamAssetBinding.workspace_id == ws))),
    }


# --------------------------------------------------------------------------- the registry

def test_every_table_is_carried_rebuilt_or_said_not_to_be():
    tables = set(sa_inspect(db_engine).get_table_names())
    carried = {f.model.__tablename__ for f in registry.build()}
    told = set(registry.REBUILT) | set(registry.NOT_CARRIED)
    assert not (tables - carried - told), f"tables the bundle says nothing about: {sorted(tables - carried - told)}"


def test_no_secret_column_is_written():
    for f in registry.build():
        for c in f.model.__table__.columns:
            if re.search(r"secret|password|api_key|(^|_)token(_hash)?$", c.name):
                assert c.name in f.drop, f"{f.name}.{c.name} would be exported"


# --------------------------------------------------------------------------- the demos

@pytest.mark.parametrize("name", ["it-services", "medium-linac"])
def test_a_demo_directory_is_a_valid_bundle(name):
    b = core.read(DEMOS / name)
    assert core.verify(b) == []
    assert all(p["status"] == "ok" for p in core.check_packages(b)), core.check_packages(b)
    m = b.manifest
    assert m["demo"]["synthetic"] is True and m["demo"]["steps"] and "fictional" in m["demo"]["notice"]
    assert m["missing_files"] == []
    people = b.rows("people")
    assert people and all(p["email"].endswith(".example") for p in people)
    text = "".join(p.read_text(errors="ignore") for p in (DEMOS / name / "records").glob("*.jsonl"))
    for word in ("password", "BEGIN PRIVATE KEY", "api_key\": \""):
        assert word not in text


@pytest.mark.parametrize("name", ["it-services", "medium-linac"])
def test_a_demo_round_trips(name, tmp_path):
    """Installed from its directory, exported, imported again elsewhere: the same packages, records, files,
    geometry, plans, placements and beam layout."""
    t = secrets.token_hex(3)
    first, second = f"rt1-{t}", f"rt2-{t}"
    try:
        view = _apply(DEMOS / name, first, tmp_path)
        assert view["ok"], view["blockers"]
        assert view["files"]["stored"] > 0 and view["not_reproduced"] == core.read(DEMOS / name).manifest["not_reproduced"]
        db = SessionLocal()
        out = tmp_path / "export"
        m = core.export(db, first, out, actor="test")
        a = _shape(db, first)
        db.close()
        assert core.verify(core.read(out)) == []
        assert m["missing_files"] == []
        source = core.read(DEMOS / name).manifest
        for fam, meta in source["families"].items():
            if fam not in ("people", "icons", "types", "workspace_packages", "ticket_workflows", "roles", "global_values",
                           "memberships"):
                assert m["families"].get(fam, {}).get("rows", 0) == meta["rows"], fam
        zip_path = core.zip_dir(out, tmp_path / "rt.zip")
        unpacked = core.unpack(zip_path, tmp_path / "unpacked")
        view = _apply(unpacked, second, tmp_path)
        assert view["ok"], view["blockers"]
        db = SessionLocal()
        b = _shape(db, second)
        db.close()
        for k in a:
            assert a[k] == b[k], k
        assert a["plans"] and a["placements"] and a["geometry"]
        if name == "medium-linac":
            assert len(a["beam_values"]) == 23 and len(a["bindings"]) == 23
    finally:
        _drop(first, second)


def test_maps_plans_and_the_tour_render_after_import(admin, tmp_path):
    """End to end through the API: the demo applied by an administrator, then its map features, floor plans,
    plan images, beam path and tour served as the web and phone read them."""
    ws = f"e2e-{secrets.token_hex(3)}"
    try:
        r = client.post("/v1/admin/bundles/demos/medium-linac/preview", json={"workspace_id": ws, "name": "E2E linac"})
        assert r.status_code == 200 and r.json()["ok"], r.text
        assert SessionLocal().get(Workspace, ws) is None            # a preview writes nothing
        r = client.post("/v1/admin/bundles/demos/medium-linac/apply", json={"workspace_id": ws, "name": "E2E linac"})
        assert r.status_code == 200 and r.json()["ok"], r.text
        h = {"X-Workspace-Id": ws}
        db = SessionLocal()
        from app.models.asset import Asset
        site = db.scalar(select(Asset).where(Asset.workspace_id == ws, Asset.name == "Valmora Linac Laboratory site"))
        db.close()
        bbox = "11.94,44.61,11.97,44.64"
        feats = client.get(f"/v1/map/features?bbox={bbox}", headers=h)
        assert feats.status_code == 200, feats.text
        kinds = Counter(f["geometry"]["type"] for f in feats.json()["features"])
        assert kinds["Polygon"] >= 10 and kinds["LineString"] >= 3 and kinds["Point"] >= 1, kinds
        plans = client.get(f"/v1/map/plans?bbox={bbox}", headers=h)
        assert plans.status_code == 200 and len(plans.json()) == 4, plans.text
        for p in plans.json():
            uid = p.get("uid") or p["plan"]["uid"]
            one = client.get(f"/v1/plans/{uid}", headers=h)
            assert one.status_code == 200
            img = client.get(f"/v1/plans/{uid}/image", headers=h)
            assert img.status_code == 200 and img.content.startswith(b"<svg"), uid
        bunker = client.get(f"/v1/plans/{plans.json()[0].get('uid') or plans.json()[0]['plan']['uid']}", headers=h)
        assert bunker.status_code == 200
        assert any(len(client.get(f"/v1/plans/{p.get('uid') or p['plan']['uid']}", headers=h).json()["placed"]) > 40
                   for p in plans.json())
        paths = client.get("/v1/beam-paths", headers=h)
        assert paths.status_code == 200 and len(paths.json()) == 2, paths.text
        main = next(p for p in paths.json() if "main dump" in p["name"])
        graph = client.get(f"/v1/beam-paths/{main['uid']}/graph", headers=h)
        assert graph.status_code == 200
        nodes = graph.json()["nodes"]
        assert len(nodes) == 21 and [n["s"] for n in nodes] == sorted(n["s"] for n in nodes)
        tour = client.get(f"/v1/workspaces/{ws}/tour", headers=h).json()["tour"]
        assert tour["synthetic"] and tour["steps"][0]["link"] == "/map"
        assert site is not None
        for step in tour["steps"]:
            link = step["link"]
            if link.startswith("/assets/"):
                assert client.get(f"/v1/assets/{link.split('/')[2]}", headers=h).status_code == 200, link
            if link.startswith("/tickets/"):
                assert client.get(f"/v1/issues/{link.split('/')[2]}", headers=h).status_code == 200, link
            if link.startswith("/documents/"):
                assert client.get(f"/v1/documents/{link.split('/')[2]}", headers=h).status_code == 200, link
    finally:
        _drop(ws)


# --------------------------------------------------------------------------- refused imports

def _blocked(root: Path, tmp: Path) -> list[dict]:
    ws = f"bad-{secrets.token_hex(3)}"
    try:
        view = _apply(root, ws, tmp)
        assert not view["ok"]
        assert SessionLocal().get(Workspace, ws) is None
        return view["blockers"]
    finally:
        _drop(ws)


def test_a_missing_file_blocks(tmp_path):
    root = _copy("it-services", tmp_path)
    victim = next(p for p in (root / "files").rglob("*") if p.is_file())
    victim.unlink()
    assert any(b["kind"] == "missing_file" for b in _blocked(root, tmp_path))


def test_a_file_missing_from_bundle_and_inventory_blocks(tmp_path):
    root = _copy("it-services", tmp_path)
    plans = _rows(root, "floor_plans")
    digest = plans[0]["storage_path"]["$file"]
    for p in (root / "files").rglob(digest):
        p.unlink()
    _reseal(root)
    assert any("not in the bundle" in b["detail"] for b in _blocked(root, tmp_path))


def test_a_changed_file_blocks(tmp_path):
    root = _copy("it-services", tmp_path)
    victim = next(p for p in (root / "files").rglob("*") if p.is_file())
    victim.write_bytes(victim.read_bytes() + b"x")
    assert any(b["kind"] in ("size", "checksum") for b in _blocked(root, tmp_path))


def test_a_broken_reference_blocks(tmp_path):
    root = _copy("it-services", tmp_path)
    rels = _rows(root, "relations")
    rels[0]["to_asset_uid"] = "no-such-asset"
    _write(root, "relations", rels)
    _reseal(root)
    assert _blocked(root, tmp_path)


def test_an_incompatible_package_blocks(tmp_path):
    root = _copy("it-services", tmp_path)
    m = json.loads((root / "manifest.json").read_text())
    m["packages"][0]["version"] = "99.0.0"
    (root / "manifest.json").write_text(json.dumps(m))
    assert any(b["kind"] == "package" for b in _blocked(root, tmp_path))
    m["packages"][0] = {**m["packages"][0], "id": "no-such-package", "version": "1.0.0"}
    (root / "manifest.json").write_text(json.dumps(m))
    assert any(b["kind"] == "package" for b in _blocked(root, tmp_path))


def test_a_newer_format_blocks(tmp_path):
    root = _copy("it-services", tmp_path)
    m = json.loads((root / "manifest.json").read_text())
    m["format_version"] = core.FORMAT_VERSION + 1
    (root / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(core.BundleError):
        core.read(root)


@pytest.mark.parametrize("geometry", [
    {"type": "Polygon", "coordinates": [[[12.0, 43.0], [12.1, 43.0]]]},          # not a closed ring
    {"type": "Polygon", "coordinates": [[[200.0, 43.0], [12.1, 43.0], [12.1, 43.1], [200.0, 43.0]]]},
    {"type": "Point", "coordinates": [12.0]},
    "not geometry",
])
def test_malformed_geometry_blocks(geometry, tmp_path):
    root = _copy("it-services", tmp_path)
    feats = _rows(root, "spatial_features")
    target = next(f for f in feats if f["role"] == ("position" if isinstance(geometry, dict) and geometry["type"] == "Point"
                                                     else "outline"))
    target["geometry"] = geometry
    _write(root, "spatial_features", feats)
    _reseal(root)
    assert _blocked(root, tmp_path)


def _zip(tmp: Path, members: dict[str, bytes], link: str | None = None) -> Path:
    path = tmp / f"z-{secrets.token_hex(3)}.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
        if link:
            info = zipfile.ZipInfo(link)
            info.external_attr = (0o120777 << 16)
            z.writestr(info, "/etc/passwd")
    return path


@pytest.mark.parametrize("name", ["../evil.json", "/abs/evil.json", "records/../../evil.json", "C:/evil.json",
                                  "records\\..\\..\\evil.json"])
def test_unsafe_archive_paths_are_refused(name, tmp_path):
    with pytest.raises(core.BundleError):
        core.unpack(_zip(tmp_path, {"manifest.json": b"{}", name: b"x"}), tmp_path / "out")
    assert not (tmp_path / "evil.json").exists()


def test_links_and_bombs_are_refused(tmp_path):
    with pytest.raises(core.BundleError):
        core.unpack(_zip(tmp_path, {"manifest.json": b"{}"}, link="records/link"), tmp_path / "out1")
    with pytest.raises(core.BundleError):
        core.unpack(_zip(tmp_path, {"manifest.json": b"{}", "records/big.jsonl": b"0" * (60 * 1024 * 1024)}),
                    tmp_path / "out2")
    with pytest.raises(core.BundleError):
        core.unpack(_write_text(tmp_path / "not.zip", "plain"), tmp_path / "out3")


def _write_text(p: Path, text: str) -> Path:
    p.write_text(text)
    return p


# --------------------------------------------------------------------------- who may

def test_people_who_are_not_administrators_are_refused(tmp_path):
    u = _user(False)
    app.dependency_overrides[get_identity] = lambda: OidcIdentity(user=u)
    try:
        assert client.get("/v1/admin/bundles").status_code == 403
        assert client.post("/v1/admin/bundles/exports", json={"workspace_id": "x"}).status_code == 403
        assert client.post("/v1/admin/bundles/demos/it-services/apply",
                           json={"workspace_id": "nope-ws", "name": "n"}).status_code == 403
        assert client.post("/v1/admin/bundles/demos/it-services/preview",
                           json={"workspace_id": "nope-ws", "name": "n"}).status_code == 403
        z = core.zip_dir(DEMOS / "it-services", tmp_path / "d.zip")
        assert client.post("/v1/admin/bundles/imports", files={"file": ("d.zip", z.read_bytes(), "application/zip")}).status_code == 403
        assert client.get(f"/v1/admin/bundles/exports/{uuid.uuid4()}/download").status_code == 403
    finally:
        app.dependency_overrides.pop(get_identity, None)
    app.dependency_overrides.pop(get_identity, None)
    assert client.get("/v1/admin/bundles").status_code in (401, 403)


def test_export_upload_and_apply_through_the_api_are_audited(admin, tmp_path):
    from app.models.portability import PortabilityEvent
    t = secrets.token_hex(3)
    src, dst = f"api1-{t}", f"api2-{t}"
    try:
        r = client.post("/v1/admin/bundles/demos/it-services/apply", json={"workspace_id": src, "name": "API source"})
        assert r.status_code == 200, r.text
        r = client.post("/v1/admin/bundles/exports", json={"workspace_id": src})
        assert r.status_code == 201, r.text
        bid = r.json()["id"]
        z = client.get(f"/v1/admin/bundles/exports/{bid}/download")
        assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
        up = client.post("/v1/admin/bundles/imports", files={"file": ("ws.zip", z.content, "application/zip")})
        assert up.status_code == 201 and up.json()["problems"] == [], up.text
        iid = up.json()["id"]
        pv = client.post(f"/v1/admin/bundles/imports/{iid}/preview", json={"workspace_id": dst, "name": "API copy"})
        assert pv.status_code == 200 and pv.json()["ok"], pv.text
        ap = client.post(f"/v1/admin/bundles/imports/{iid}/apply", json={"workspace_id": dst, "name": "API copy"})
        assert ap.status_code == 200 and ap.json()["ok"], ap.text
        # The administrator owns the new workspace; nobody else got access without asking for it.
        from app.models.membership import Membership
        db = SessionLocal()
        members = {m.user_id for m in db.scalars(select(Membership).where(Membership.workspace_id == dst))}
        assert members == {admin.id}
        events = list(db.scalars(select(PortabilityEvent).where(PortabilityEvent.actor == admin.email)))
        kinds = {(e.subject_kind, e.kind, (e.detail or {}).get("outcome")) for e in events}
        db.close()
        assert ("bundle-export", "export", "exported") in kinds
        assert ("bundle-export", "download", None) in kinds
        assert ("bundle-import", "upload", "checked") in kinds
        assert ("bundle-import", "preview", "previewed") in kinds
        assert ("bundle-import", "apply", "imported") in kinds
        assert all("format_version" in (e.detail or {}) for e in events if e.kind in ("apply", "preview", "export"))
        client.delete(f"/v1/admin/bundles/exports/{bid}")
        client.delete(f"/v1/admin/bundles/imports/{iid}")
    finally:
        _drop(src, dst)


def test_a_bad_upload_is_refused_and_audited(admin, tmp_path):
    from app.models.portability import PortabilityEvent
    bad = _zip(tmp_path, {"manifest.json": b"{}", "../x": b"y"})
    r = client.post("/v1/admin/bundles/imports", files={"file": ("bad.zip", bad.read_bytes(), "application/zip")})
    assert r.status_code == 422
    db = SessionLocal()
    e = db.scalar(select(PortabilityEvent).where(PortabilityEvent.actor == admin.email, PortabilityEvent.kind == "upload"))
    db.close()
    assert e is not None and e.detail["outcome"] == "refused"


# --------------------------------------------------------------------------- again

def test_importing_again_is_refused_into_the_same_workspace_and_renames_into_another(tmp_path):
    t = secrets.token_hex(3)
    a, b = f"rep1-{t}", f"rep2-{t}"
    try:
        first = _apply(DEMOS / "it-services", a, tmp_path)
        assert first["ok"]
        again = _apply(DEMOS / "it-services", a, tmp_path)
        assert not again["ok"] and again["blockers"][0]["kind"] == "workspace_exists"
        other = _apply(DEMOS / "it-services", b, tmp_path)
        assert other["ok"] and other["renamed_count"] > 0
        db = SessionLocal()
        sa, sb = _shape(db, a), _shape(db, b)
        db.close()
        for k in ("assets", "names", "relations", "tickets", "geometry", "plans", "placements"):
            assert sa[k] == sb[k], k
        # The two copies share no record.
        from app.models.asset import Asset
        db = SessionLocal()
        ua = set(db.scalars(select(Asset.uid).where(Asset.workspace_id == a)))
        ub = set(db.scalars(select(Asset.uid).where(Asset.workspace_id == b)))
        db.close()
        assert ua and ub and not (ua & ub)
    finally:
        _drop(a, b)


def test_document_links_and_the_tour_follow_renamed_records(tmp_path):
    t = secrets.token_hex(3)
    a, b = f"lnk1-{t}", f"lnk2-{t}"
    try:
        assert _apply(DEMOS / "it-services", a, tmp_path)["ok"]
        assert _apply(DEMOS / "it-services", b, tmp_path)["ok"]
        from app.models.app_setting import AppSetting
        from app.models.asset import Asset
        from app.models.document import Document, DocumentRevision
        db = SessionLocal()
        uids = set(db.scalars(select(Asset.uid).where(Asset.workspace_id == b)))
        tour = db.get(AppSetting, f"demo.tour.{b}").value
        for step in tour["steps"]:
            if step["link"].startswith("/assets/"):
                assert step["link"].split("/")[2] in uids, step
        arch = db.scalar(select(Document).where(Document.workspace_id == b, Document.title == "Campus network architecture"))
        body = db.get(DocumentRevision, arch.current_revision_uid).body_markdown
        db.close()
        linked = re.findall(r"\(/assets/([^)]+)\)", body)
        assert linked and all(x in uids for x in linked)
    finally:
        _drop(a, b)
