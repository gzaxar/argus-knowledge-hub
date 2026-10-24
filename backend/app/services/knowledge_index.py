"""What the records *say*, searchable by meaning: the retrieval half of Ask ARGUS (RAG).

The inventory is answered by exact lookups (search_objects, the graph): "how many magnets" needs all 79,
not the 8 most similar. What this adds is the written knowledge, where the words of the question are rarely
the words of the answer: a procedure's text, a ticket and its comments (what went wrong and how it was
fixed), the comments on equipment, and the text of attached files (datasheets and manuals, page by page).

Each source is cut into passages, embedded with the workspace's embedding model, and kept in
`knowledge_chunks` (pgvector) with a full-text column beside the vector. A search ranks passages both ways,
by meaning and by words, and fuses the two rankings (reciprocal rank fusion): meaning finds "pompa ionica"
for "ion pump", words find the exact part number a vector blurs.

Who may read what is decided when searching, from the records themselves, by the rules the rest of the hub
applies: a workspace's own records and the ones flagged shared, restricted classes only with the grant, and
a confidential (riservato) document only where the workspace lets confidential text reach a model.

Indexing is incremental: a source whose text has not changed since it was indexed is not embedded again.
Run it from the AI settings page, or `python -m app.services.knowledge_index <workspace|all>`.
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Iterator, Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.asset_subresources import AssetComment
from app.models.attachment import Attachment
from app.models.document import Document, DocumentRevision
from app.models.issue import Issue, IssueComment
from app.services.llm import Endpoint, LLMError, embed, rerank

CHUNK_CHARS = 1200
OVERLAP_CHARS = 150
EMBED_BATCH = 32
# Batches in flight at once: a long manual is hundreds of passages, and one request at a time leaves the
# gateway idle between them.
EMBED_PARALLEL = 4
EMBED_CHARS = 6000
MAX_FILE_PAGES = 400
MAX_FILE_CHARS = 600_000
# Qwen3-Embedding is trained with an instruction on the query side only.
QUERY_INSTRUCTION = "Instruct: Given a question about accelerator equipment, retrieve passages that answer it\nQuery: "
KINDS = ("document", "ticket", "ticket_comment", "attachment", "asset_comment")
READABLE = re.compile(r"\.(pdf|docx|xlsx|xlsm|txt|md|csv|eml)$", re.I)

DDL = [
    "CREATE EXTENSION IF NOT EXISTS vector",
    """CREATE TABLE IF NOT EXISTS knowledge_chunks (
        id bigserial PRIMARY KEY,
        workspace_id text NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        shared boolean NOT NULL DEFAULT false,
        confidential boolean NOT NULL DEFAULT false,
        source_kind text NOT NULL,
        source_uid text NOT NULL,
        parent_kind text,
        parent_uid text,
        title text NOT NULL,
        locator text,
        seq integer NOT NULL,
        body text NOT NULL,
        content_hash text NOT NULL,
        model text NOT NULL,
        embedding vector,
        tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', coalesce(title, '') || ' ' || body)) STORED,
        indexed_at timestamptz NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_workspace ON knowledge_chunks (workspace_id)",
    "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_source ON knowledge_chunks (source_kind, source_uid)",
    "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_tsv ON knowledge_chunks USING gin (tsv)",
    """CREATE TABLE IF NOT EXISTS knowledge_index_runs (
        workspace_id text PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
        state text NOT NULL,
        started_at timestamptz,
        finished_at timestamptz,
        result jsonb
    )""",
]


# --------------------------------------------------------------------------- the store

def pgvector_available(db: Session) -> bool:
    return bool(db.execute(text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")).scalar())


def store_ready(db: Session) -> bool:
    return bool(db.execute(text("SELECT to_regclass('knowledge_chunks') IS NOT NULL")).scalar())


def ensure_store(db: Session) -> None:
    """Creates the extension and the tables when the database can have them; raises a person-facing
    LLMError when it cannot (a Postgres without pgvector)."""
    if store_ready(db):
        return
    if not pgvector_available(db):
        raise LLMError("This database has no pgvector extension: run Postgres with pgvector "
                       "(the pgvector/pgvector image) to index the written knowledge.")
    for statement in DDL:
        db.execute(text(statement))
    db.commit()


def _vector(values: list[float]) -> str:
    return "[" + ",".join(f"{v:.6g}" for v in values) + "]"


# --------------------------------------------------------------------------- the sources

@dataclass
class Source:
    kind: str
    uid: str
    title: str
    parts: list[tuple[Optional[str], str]]          # (locator, text)
    parent_kind: Optional[str] = None
    parent_uid: Optional[str] = None
    shared: bool = False
    confidential: bool = False
    hash: str = field(default="")

    def digest(self, model: str) -> str:
        h = hashlib.sha256(model.encode())
        h.update(self.title.encode())
        for locator, body in self.parts:
            h.update((locator or "").encode())
            h.update(body.encode())
        return h.hexdigest()


def _sections(markdown: str) -> list[tuple[Optional[str], str]]:
    """A document's text by heading, so a passage can say which section it is from."""
    out, heading, lines = [], None, []
    for line in (markdown or "").splitlines():
        m = re.match(r"^#{1,6}\s+(.*)", line)
        if m:
            if "".join(lines).strip():
                out.append((heading, "\n".join(lines).strip()))
            heading, lines = m.group(1).strip(), []
        else:
            lines.append(line)
    if "".join(lines).strip():
        out.append((heading, "\n".join(lines).strip()))
    return out


def _file_parts(path: str, filename: str, mime: Optional[str]) -> list[tuple[Optional[str], str]]:
    """A file's text, page by page for a PDF. Unreadable files (scans, damaged) give nothing."""
    with open(path, "rb") as f:
        content = f.read()
    if filename.lower().endswith(".pdf") or (mime or "").endswith("pdf"):
        from pypdf import PdfReader
        try:
            reader = PdfReader(io.BytesIO(content))
        except Exception:  # noqa: BLE001 — damaged or encrypted: nothing to index
            return []
        parts, total = [], 0
        for n, page in enumerate(reader.pages[:MAX_FILE_PAGES], start=1):
            try:
                body = (page.extract_text() or "").strip()
            except Exception:  # noqa: BLE001
                body = ""
            if body:
                parts.append((f"page {n}", body))
                total += len(body)
                if total > MAX_FILE_CHARS:
                    break
        return parts
    from app.intake.files import UnreadableFile, extract
    try:
        body, _refs = extract(content, filename, mime)
    except UnreadableFile:
        return []
    return [(None, body)] if body.strip() else []


def sources(db: Session, workspace_id: str) -> Iterator[Source]:
    """Everything with text in a workspace, as sources to index."""
    for doc in db.scalars(select(Document).where(Document.workspace_id == workspace_id,
                                                 Document.retired_at.is_(None))):
        revision = db.get(DocumentRevision, doc.current_revision_uid) if doc.current_revision_uid else None
        if revision is None:
            continue
        body = revision.body_markdown or ""
        steps = "\n".join(str(s.get("text") or s.get("title") or "") for s in (revision.steps or [])
                          if isinstance(s, dict))
        parts = _sections(body + ("\n\n# Steps\n" + steps if steps.strip() else ""))
        summary = (revision.attributes or {}).get("argus_summary")
        if isinstance(summary, str) and summary.strip():
            parts = [("Summary", summary.strip()), *parts]       # what the document is, said in two sentences
        if parts:
            yield Source("document", doc.uid, f"{doc.code} {doc.title}", parts,
                         shared=bool(doc.is_global) and doc.confidentiality != "riservato",
                         confidential=doc.confidentiality == "riservato")
    issues = {i.uid: i for i in db.scalars(select(Issue).where(Issue.workspace_id == workspace_id))}
    for issue in issues.values():
        a = issue.attributes or {}
        extra = "\n".join(f"{label}: {a[k]}" for k, label in (("argus_root_cause", "Root cause"),
                                                               ("argus_resolution", "Resolution"),
                                                               ("argus_impact", "Impact")) if a.get(k))
        body = "\n\n".join(x for x in (issue.description or "", extra) if x.strip())
        key = a.get("argus_source_key")
        yield Source("ticket", issue.uid, f"{key + ' ' if key else ''}{issue.title}", [(None, body or issue.title)])
    if issues:
        for c in db.scalars(select(IssueComment).where(IssueComment.issue_uid.in_(list(issues)))):
            if (c.body or "").strip():
                yield Source("ticket_comment", c.uid, f"Comment on {issues[c.issue_uid].title}", [(None, c.body)],
                             parent_kind="ticket", parent_uid=c.issue_uid)
    assets = {u: (k, n, g) for u, k, n, g in db.execute(
        select(Asset.uid, Asset.key, Asset.name, Asset.is_global).where(Asset.workspace_id == workspace_id))}
    if assets:
        for c in db.scalars(select(AssetComment).where(AssetComment.asset_uid.in_(list(assets)))):
            if (c.text or "").strip():
                key, name, shared = assets[c.asset_uid]
                yield Source("asset_comment", c.uid, f"Comment on {key} {name}", [(None, c.text)],
                             parent_kind="asset", parent_uid=c.asset_uid, shared=bool(shared))
    for att in db.scalars(select(Attachment).where(Attachment.workspace_id == workspace_id)):
        if not READABLE.search(att.filename or "") and "pdf" not in (att.mime_type or ""):
            continue
        if not att.storage_path or not os.path.exists(att.storage_path):
            continue
        if att.asset_uid:
            key, name, shared = assets.get(att.asset_uid) or (None, None, False)
            parent, title = ("asset", att.asset_uid), f"{att.filename} ({key} {name})" if key else att.filename
        elif att.issue_uid:
            shared, parent = False, ("ticket", att.issue_uid)
            title = f"{att.filename} (ticket {issues[att.issue_uid].title})" if att.issue_uid in issues else att.filename
        else:
            shared, parent, title = False, ("document_revision", att.document_revision_uid), att.filename
        yield _LazyFile(att, title, parent, bool(shared))


class _LazyFile(Source):
    """An attachment, read only when its hash says it changed: reading every PDF on every run would make an
    incremental run as slow as the first."""

    def __init__(self, att: Attachment, title: str, parent: tuple, shared: bool):
        super().__init__("attachment", att.uid, title, [], parent_kind=parent[0], parent_uid=parent[1],
                         shared=shared)
        self.att = att

    def digest(self, model: str) -> str:
        h = hashlib.sha256(model.encode())
        h.update(self.title.encode())
        h.update((self.att.sha256 or f"{self.att.file_size}:{self.att.updated_at}").encode())
        return h.hexdigest()

    def load(self) -> None:
        if not self.parts:
            self.parts = _file_parts(self.att.storage_path, self.att.filename, self.att.mime_type)


def _chunks(parts: list[tuple[Optional[str], str]]) -> list[tuple[Optional[str], str]]:
    """Passages of about CHUNK_CHARS, cut at paragraph ends where possible, overlapping a little so a
    sentence on a boundary is in both."""
    out = []
    for locator, body in parts:
        body = re.sub(r"[ \t]+", " ", body).strip()
        start = 0
        while start < len(body):
            end = min(len(body), start + CHUNK_CHARS)
            if end < len(body):
                cut = max(body.rfind("\n\n", start, end), body.rfind(". ", start, end))
                if cut > start + CHUNK_CHARS // 2:
                    end = cut + 1
            piece = body[start:end].strip()
            if piece:
                out.append((locator, piece))
            if end >= len(body):
                break
            start = max(end - OVERLAP_CHARS, start + 1)
    return out


# --------------------------------------------------------------------------- indexing

def _embed_all(endpoint: Endpoint, texts: list[str]) -> list[list[float]]:
    """Vectors for many texts, in order: batches sent a few at a time."""
    batches = [texts[i:i + EMBED_BATCH] for i in range(0, len(texts), EMBED_BATCH)]
    if len(batches) == 1:
        return embed(endpoint, batches[0])
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=EMBED_PARALLEL) as pool:
        results = list(pool.map(lambda b: embed(endpoint, b), batches))
    return [v for batch in results for v in batch]


def index_workspace(db: Session, workspace_id: str, endpoint: Endpoint, log=None) -> dict:
    """Brings a workspace's passages up to date: new and changed sources embedded, removed ones dropped."""
    ensure_store(db)
    if not endpoint.embedding_model:
        raise LLMError("This workspace's AI endpoint has no embedding model: set one in the AI settings.")
    model = endpoint.embedding_model
    started = time.monotonic()
    db.execute(text("""INSERT INTO knowledge_index_runs (workspace_id, state, started_at) VALUES (:w, 'running', now())
                       ON CONFLICT (workspace_id) DO UPDATE SET state = 'running', started_at = now()"""),
               {"w": workspace_id})
    db.commit()
    existing = {(k, u): h for k, u, h in db.execute(text(
        "SELECT DISTINCT source_kind, source_uid, content_hash FROM knowledge_chunks "
        "WHERE workspace_id = :w AND model = :m"), {"w": workspace_id, "m": model})}
    counts = {"sources": 0, "indexed": 0, "unchanged": 0, "removed": 0, "chunks": 0, "unreadable": 0}
    failed: list[str] = []
    seen = set()
    for source in sources(db, workspace_id):
        counts["sources"] += 1
        seen.add((source.kind, source.uid))
        digest = source.digest(model)
        if existing.get((source.kind, source.uid)) == digest:
            counts["unchanged"] += 1
            continue
        if isinstance(source, _LazyFile):
            try:
                source.load()
            except OSError as e:
                failed.append(f"{source.title}: {e}")
                continue
        pieces = _chunks(source.parts)
        db.execute(text("DELETE FROM knowledge_chunks WHERE workspace_id = :w AND source_kind = :k AND source_uid = :u"),
                   {"w": workspace_id, "k": source.kind, "u": source.uid})
        if not pieces:
            counts["unreadable"] += 1
            db.commit()
            continue
        try:
            vectors = _embed_all(endpoint, [f"{source.title}\n{loc or ''}\n{body}"[:EMBED_CHARS] for loc, body in pieces])
        except LLMError as e:
            db.rollback()
            failed.append(f"{source.title}: {e}")
            if len(failed) >= 5 and not counts["indexed"]:
                break                                   # the endpoint is down, not one file: stop trying
            continue
        for seq, ((locator, body), vector) in enumerate(zip(pieces, vectors)):
            db.execute(text("""INSERT INTO knowledge_chunks (workspace_id, shared, confidential, source_kind, source_uid,
                    parent_kind, parent_uid, title, locator, seq, body, content_hash, model, embedding)
                VALUES (:w, :shared, :conf, :k, :u, :pk, :pu, :title, :loc, :seq, :body, :hash, :model, CAST(:vec AS vector))"""),
                       {"w": workspace_id, "shared": source.shared, "conf": source.confidential, "k": source.kind,
                        "u": source.uid, "pk": source.parent_kind, "pu": source.parent_uid, "title": source.title[:500],
                        "loc": locator, "seq": seq, "body": body, "hash": digest, "model": model,
                        "vec": _vector(vector)})
        db.commit()
        counts["indexed"] += 1
        counts["chunks"] += len(pieces)
        if log:
            log(f"{source.kind} {source.title[:70]}: {len(pieces)} passages")
    gone = [key for key in existing if key not in seen]
    for kind, uid in gone:
        db.execute(text("DELETE FROM knowledge_chunks WHERE workspace_id = :w AND source_kind = :k AND source_uid = :u"),
                   {"w": workspace_id, "k": kind, "u": uid})
    counts["removed"] = len(gone)
    # Passages of another embedding model can be compared with nothing a search embeds now.
    db.execute(text("DELETE FROM knowledge_chunks WHERE workspace_id = :w AND model <> :m"), {"w": workspace_id, "m": model})
    result = {**counts, "failed": failed[:20], "seconds": round(time.monotonic() - started, 1), "model": model}
    db.execute(text("""UPDATE knowledge_index_runs SET state = :s, finished_at = now(), result = CAST(:r AS jsonb)
                       WHERE workspace_id = :w"""),
               {"w": workspace_id, "s": "failed" if failed and not counts["indexed"] and counts["sources"] > counts["unchanged"]
                else "done", "r": __import__("json").dumps(result)})
    db.commit()
    return result


def status(db: Session, workspace_id: str) -> dict:
    """What is indexed here, and whether it can be."""
    if not store_ready(db):
        return {"ready": False, "pgvector": pgvector_available(db), "passages": {}, "sources": {}, "run": None}
    passages = dict(db.execute(text("SELECT source_kind, count(*) FROM knowledge_chunks WHERE workspace_id = :w "
                                    "GROUP BY 1"), {"w": workspace_id}).all())
    counted = dict(db.execute(text("SELECT source_kind, count(DISTINCT source_uid) FROM knowledge_chunks "
                                   "WHERE workspace_id = :w GROUP BY 1"), {"w": workspace_id}).all())
    run = db.execute(text("SELECT state, started_at, finished_at, result FROM knowledge_index_runs WHERE workspace_id = :w"),
                     {"w": workspace_id}).mappings().first()
    return {"ready": True, "pgvector": True, "passages": passages, "sources": counted,
            "run": dict(run) if run else None}


# --------------------------------------------------------------------------- searching

def _visible(db: Session, workspace_id: str, row, confidential_ok: bool) -> Optional[dict]:
    """Whether the asking workspace may read this passage, and the record to cite it by."""
    from app.services.visibility import asset_visible_in, can_see
    kind = row["source_kind"]
    if kind == "document":
        doc = db.get(Document, row["source_uid"])
        if doc is None or doc.retired_at is not None:
            return None
        if doc.confidentiality == "riservato" and not (doc.workspace_id == workspace_id and confidential_ok):
            return None
        if doc.workspace_id != workspace_id and not doc.is_global:
            return None
        return {"uid": doc.uid, "code": doc.code}
    if kind in ("ticket", "ticket_comment") or row["parent_kind"] == "ticket":
        uid = row["source_uid"] if kind == "ticket" else row["parent_uid"]
        issue = db.get(Issue, uid)
        if issue is None or issue.workspace_id != workspace_id or not can_see(issue):
            return None
        key = (issue.attributes or {}).get("argus_source_key")
        return {"uid": issue.uid, **({"source_key": key} if key else {}), "title": issue.title}
    if row["parent_kind"] == "asset":
        asset = db.get(Asset, row["parent_uid"])
        if asset is None or not asset_visible_in(asset, workspace_id):
            return None
        return {"uid": asset.uid, "key": asset.key, "name": asset.name}
    if row["parent_kind"] == "document_revision":
        revision = db.get(DocumentRevision, row["parent_uid"])
        doc = db.get(Document, revision.document_uid) if revision else None
        if doc is None or (doc.workspace_id != workspace_id and not doc.is_global):
            return None
        if doc.confidentiality == "riservato" and not (doc.workspace_id == workspace_id and confidential_ok):
            return None
        return {"uid": doc.uid, "code": doc.code}
    return None


def search(db: Session, workspace_id: str, endpoint: Endpoint, query: str, kinds: Optional[list] = None,
           limit: int = 8, confidential_ok: bool = False) -> dict:
    """The passages that best answer a question, by meaning and by words, that this workspace may read."""
    if not store_ready(db):
        return {"available": False, "reason": "The written knowledge has not been indexed: the database needs "
                                              "pgvector, and the index has to be built (AI settings)."}
    q = (query or "").strip()
    if not q:
        return {"available": True, "results": []}
    kinds = [k for k in (kinds or []) if k in KINDS] or list(KINDS)
    scope = "(workspace_id = :w OR shared) AND source_kind = ANY(:kinds)"
    params = {"w": workspace_id, "kinds": kinds}
    ranked: dict[int, float] = {}
    rows: dict[int, dict] = {}
    columns = "id, workspace_id, source_kind, source_uid, parent_kind, parent_uid, title, locator, body"
    if endpoint.embedding_model:
        try:
            vector = embed(endpoint, [QUERY_INSTRUCTION + q])[0]
        except LLMError:
            vector = None
        if vector is not None:
            for rank, row in enumerate(db.execute(text(
                    f"SELECT {columns} FROM knowledge_chunks WHERE {scope} AND model = :m AND embedding IS NOT NULL "
                    "ORDER BY embedding <=> CAST(:v AS vector) LIMIT 60"),
                    {**params, "m": endpoint.embedding_model, "v": _vector(vector)}).mappings()):
                rows[row["id"]] = dict(row)
                ranked[row["id"]] = ranked.get(row["id"], 0) + 1 / (60 + rank)
    for rank, row in enumerate(db.execute(text(
            f"SELECT {columns} FROM knowledge_chunks WHERE {scope} AND tsv @@ websearch_to_tsquery('simple', :q) "
            "ORDER BY ts_rank(tsv, websearch_to_tsquery('simple', :q)) DESC LIMIT 60"), {**params, "q": q}).mappings()):
        rows[row["id"]] = dict(row)
        ranked[row["id"]] = ranked.get(row["id"], 0) + 1 / (60 + rank)
    wanted = max(1, min(limit, 20))
    # With a re-ranker, a wider pool is gathered first and the re-ranker orders it by how well each passage
    # answers the question; the hybrid ranking only chooses which passages it sees.
    pool = min(40, wanted * 4) if endpoint.rerank_model else wanted
    results, per_source, said = [], {}, set()
    for cid in sorted(ranked, key=ranked.get, reverse=True):
        row = rows[cid]
        source = (row["source_kind"], row["source_uid"])
        # One file attached to several records is several sources with the same passages: say it once.
        text_key = hashlib.sha256(row["body"].encode()).hexdigest()
        if per_source.get(source, 0) >= 3 or text_key in said:
            continue
        record = _visible(db, workspace_id, row, confidential_ok)
        if record is None:
            continue
        per_source[source] = per_source.get(source, 0) + 1
        said.add(text_key)
        results.append({"kind": row["source_kind"], "title": row["title"], "where": row["locator"],
                        "excerpt": row["body"][:1200], "record": record, "score": round(ranked[cid], 4)})
        if len(results) >= pool:
            break
    reranked = False
    if endpoint.rerank_model and len(results) > 1:
        try:
            order = rerank(endpoint, q, [f"{r['title']}\n{r['excerpt']}" for r in results])
            if order:
                picked = [dict(results[i], rerank_score=round(score, 4)) for i, score in order if 0 <= i < len(results)]
                results, reranked = picked, True
        except LLMError:
            pass                                    # the search's own order stands
    return {"available": True, "results": results[:wanted], "reranked": reranked}


# --------------------------------------------------------------------------- the semantic graph

def _record_of(db: Session, row) -> Optional[tuple[str, str]]:
    """The record a passage speaks for: a document (its text or a revision's file), a ticket (its text, a
    comment, a file), a piece of equipment (a comment on it, a file)."""
    kind, parent = row["source_kind"], row["parent_kind"]
    if kind == "document":
        return "document", row["source_uid"]
    if kind == "ticket":
        return "ticket", row["source_uid"]
    if parent == "ticket":
        return "ticket", row["parent_uid"]
    if parent == "asset":
        return "asset", row["parent_uid"]
    if parent == "document_revision":
        revision = db.get(DocumentRevision, row["parent_uid"])
        return ("document", revision.document_uid) if revision else None
    return None


def _own_passages(db: Session, kind: str, uid: str, model: str, limit: int = 6) -> list[dict]:
    if kind == "document":
        revisions = [r for (r,) in db.execute(select(DocumentRevision.uid).where(DocumentRevision.document_uid == uid))]
        where = ("((source_kind = 'document' AND source_uid = :u) OR "
                 "(parent_kind = 'document_revision' AND parent_uid = ANY(:revs)))")
        params = {"u": uid, "revs": revisions}
    elif kind == "ticket":
        where, params = "((source_kind = 'ticket' AND source_uid = :u) OR (parent_kind = 'ticket' AND parent_uid = :u))", {"u": uid}
    elif kind == "asset":
        where, params = "(parent_kind = 'asset' AND parent_uid = :u)", {"u": uid}
    else:
        return []
    return [dict(r) for r in db.execute(text(
        f"SELECT body, embedding::text AS vec FROM knowledge_chunks WHERE {where} AND model = :m "
        "AND embedding IS NOT NULL ORDER BY source_kind, seq LIMIT :n"), {**params, "m": model, "n": limit}).mappings()]


def _describe(db: Session, kind: str, uid: str) -> Optional[str]:
    """What a record without indexed text is, to search by: its key, name, type and description."""
    if kind == "asset":
        a = db.get(Asset, uid)
        if a is None:
            return None
        attrs = a.attributes or {}
        return " ".join(str(x) for x in (a.key, a.name, a.type, attrs.get("description"), attrs.get("manufacturer"),
                                         attrs.get("model")) if x)
    if kind == "ticket":
        i = db.get(Issue, uid)
        return f"{i.title}\n{i.description or ''}" if i else None
    if kind == "document":
        d = db.get(Document, uid)
        return f"{d.code} {d.title}" if d else None
    return None


def related(db: Session, workspace_id: str, kind: str, uid: str, endpoint: Optional[Endpoint] = None,
            limit: int = 10, min_score: float = 0.3, confidential_ok: bool = False) -> dict:
    """The records whose written knowledge is about the same thing as this one's — the semantic graph beside
    the relation graph. Each comes with how close it is (cosine similarity of the closest passages, 0 to 1)
    and the two passages that are closest, so the link explains itself. Only what this workspace may read."""
    if not store_ready(db):
        return {"available": False, "reason": "The written knowledge has not been indexed (AI settings)."}
    model = (endpoint.embedding_model if endpoint and endpoint.embedding_model else None) or db.execute(text(
        "SELECT model FROM knowledge_chunks WHERE workspace_id = :w GROUP BY model ORDER BY count(*) DESC LIMIT 1"),
        {"w": workspace_id}).scalar()
    if not model:
        return {"available": True, "related": [], "from": "nothing indexed"}
    own = _own_passages(db, kind, uid, model)
    basis = "passages"
    if not own and endpoint and endpoint.embedding_model:
        description = _describe(db, kind, uid)
        if description:
            try:
                own = [{"body": description, "vec": _vector(embed(endpoint, [description])[0])}]
                basis = "description"
            except LLMError:
                own = []
    best: dict[tuple, dict] = {}
    for mine in own:
        for row in db.execute(text(
                "SELECT source_kind, source_uid, parent_kind, parent_uid, title, body, "
                "1 - (embedding <=> CAST(:v AS vector)) AS score FROM knowledge_chunks "
                "WHERE (workspace_id = :w OR shared) AND model = :m AND embedding IS NOT NULL "
                "ORDER BY embedding <=> CAST(:v AS vector) LIMIT 40"),
                {"v": mine["vec"], "w": workspace_id, "m": model}).mappings():
            target = _record_of(db, row)
            if target is None or target == (kind, uid) or row["score"] < min_score:
                continue
            if target in best and best[target]["score"] >= row["score"]:
                continue
            record = _visible(db, workspace_id, row, confidential_ok)
            if record is None:
                continue
            best[target] = {"kind": target[0], "uid": target[1], "record": record, "score": round(float(row["score"]), 3),
                            "excerpt": row["body"][:400], "matched": mine["body"][:400], "title": row["title"]}
    ranked = sorted(best.values(), key=lambda r: r["score"], reverse=True)[:max(1, min(limit, 30))]
    return {"available": True, "related": ranked, "from": basis if own else "nothing indexed"}


# --------------------------------------------------------------------------- the command line

def main(argv: list[str]) -> None:
    from app.db import SessionLocal
    from app.models.workspace import Workspace
    from app.routers.ai import endpoint_for
    from app.services.ai_config import resolve
    if not argv:
        print("usage: python -m app.services.knowledge_index <workspace|all>")
        sys.exit(2)
    db = SessionLocal()
    targets = [w.id for w in db.query(Workspace)] if argv[0] == "all" else argv
    for ws in targets:
        config, _from = resolve(db, ws)
        if config is None or not config.embedding_model:
            print(f"{ws}: no AI endpoint with an embedding model, skipped")
            continue
        try:
            result = index_workspace(db, ws, endpoint_for(config), log=lambda m: print("  " + m))
        except LLMError as e:
            print(f"{ws}: {e}")
            continue
        print(f"{ws}: {result}")


if __name__ == "__main__":
    main(sys.argv[1:])
