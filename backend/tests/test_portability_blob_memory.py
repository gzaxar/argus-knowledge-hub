"""Reading thousands of attachments for an export gives the memory back as it goes (exporter.RELEASE_EVERY)."""
from types import SimpleNamespace

from app.portability import exporter
from app.portability.families import FAMILIES


def test_inspecting_many_files_releases_memory_every_few_files(tmp_path, monkeypatch):
    released = []
    monkeypatch.setattr(exporter, "release_memory", lambda: released.append(1) or True)
    fam = next(f for f in FAMILIES if f.name == "icons")
    blobs = exporter.Blobs(None, {}, False)
    n = exporter.RELEASE_EVERY * 2 + 3
    for i in range(n):
        p = tmp_path / f"icon-{i}.svg"
        p.write_text(f"<svg><title>icon {i}</title></svg>")
        obj = SimpleNamespace(uid=f"u{i}", storage_path=str(p))
        blobs.add(obj, fam, "storage_path", "file", {"uid": f"u{i}", "filename": p.name, "mime_type": "image/svg+xml"})
    assert blobs.opened == n and len(released) == 2


def test_releasing_memory_works_where_there_is_no_glibc():
    assert exporter.release_memory() in (True, False)
