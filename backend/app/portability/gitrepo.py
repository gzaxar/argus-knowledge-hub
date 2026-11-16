"""The Git portability project: publishing checkpoints, and fetching them into quarantine.

Publishing (`publish`) adds a checkpoint under `exports/checkpoints/<export-id>/` — never over an
existing one — refreshes the reviewable views (`format/`, `catalogue/`, `governance/`), scans every
added file for secrets, and makes one SSH-signed commit and one signed annotated tag:

    export/full/<date>@cp<checkpoint>-<vector hash>
    export/workspace/<workspace>/<date>@cp<checkpoint>-<vector hash>
    export/increment/<full|workspace>/<date>@cp<checkpoint>-<vector hash>

Only small, reviewable files go into Git (`git_files`): bulk chunks and blobs are artifacts, so
repeated full checkpoints do not accumulate data volume in Git history.

It pushes without force. Protecting tags against deletion and movement is the Git server's job
(protected tags, no force push); docs/operations.md lists the settings.

Fetching (`fetch_into_quarantine`) treats the repository as hostile data. It never checks out a
working tree, never runs a hook, filter or submodule, and reads objects one by one through
`git cat-file`, after refusing symbolic links, submodules, executables outside `tools/`, unsafe
paths and oversized objects. It accepts a signed annotated tag, or a signed commit named by its
full hash — never a branch.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Optional

import yaml

from app.portability import REPOSITORY_LAYOUT, chunks, secret_scan
from app.portability.signing import Signer

IDENTITY_FILE = ".argus-portability.json"
CHECKPOINTS = "exports/checkpoints"
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")
LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"
EXECUTABLE_ALLOWED = ("tools/",)


class GitError(ValueError):
    def __init__(self, message: str, code: str = "git_refused", detail: Optional[dict] = None):
        super().__init__(message)
        self.code, self.detail = code, detail or {}


def _env(extra: Optional[dict] = None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
                "GIT_AUTHOR_NAME": os.environ.get("ARGUS_PORTABILITY_GIT_NAME", "ARGUS portability"),
                "GIT_AUTHOR_EMAIL": os.environ.get("ARGUS_PORTABILITY_GIT_EMAIL", "portability@argus.invalid"),
                "GIT_LFS_SKIP_SMUDGE": "1"})
    env["GIT_COMMITTER_NAME"], env["GIT_COMMITTER_EMAIL"] = env["GIT_AUTHOR_NAME"], env["GIT_AUTHOR_EMAIL"]
    env.update(extra or {})
    return env


_HARDENED = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "protocol.ext.allow=never",
             "-c", "submodule.recurse=false", "-c", "core.symlinks=false", "-c", "transfer.fsckObjects=true"]


def git(args: list[str], cwd: Path, *, check: bool = True, input: Optional[bytes] = None,
        signer: Optional[Signer] = None, allowed: Optional[Path] = None, env: Optional[dict] = None,
        binary: bool = False):
    cfg = list(_HARDENED)
    if signer is not None:
        cfg += ["-c", "gpg.format=ssh", "-c", f"user.signingkey={signer.key_path}"]
    if allowed is not None:
        cfg += ["-c", "gpg.format=ssh", "-c", f"gpg.ssh.allowedSignersFile={allowed}"]
    r = subprocess.run(["git", *cfg, *args], cwd=cwd, capture_output=True, input=input, env=_env(env), timeout=600)
    if check and r.returncode != 0:
        raise GitError(f"git {args[0]} failed: {r.stderr.decode(errors='replace').strip()[:400]}", code="git_failed")
    return r if binary else type("R", (), {"returncode": r.returncode, "stdout": r.stdout.decode(errors="replace"),
                                           "stderr": r.stderr.decode(errors="replace")})()


GIT_FILES = ("manifest.json", "checksums.sha256", "signature.json", "blobs.manifest.ndjson", "workspaces.ndjson",
             "relation-registry.json", "reconciliation.json")


def git_files(manifest: dict) -> list[str]:
    """What of a checkpoint goes into Git: the manifest, checksums, signature, the review files and the
    chunks stored in Git. Every other chunk is an artifact, named in the manifest."""
    out = list(GIT_FILES)
    for fam in manifest["families"].values():
        out += [c["file"] for c in fam["chunks"] if c.get("storage") == "git"]
    return out


def tag_name(manifest: dict) -> str:
    """`…/<date>@cp<checkpoint>-<vector hash, 12>`: the checkpoint number never repeats, and two
    different watermark vectors never share a tag."""
    date = manifest["watermark"]["snapshot_time"][:10]
    w = f"cp{manifest['watermark']['checkpoint_sequence']}-{manifest['watermark']['vector_sha256'][:12]}"
    if manifest["mode"] == "incremental":
        # An increment and a checkpoint can share a watermark; their tags must not collide.
        scope = "full" if not manifest.get("selective") else _scope(manifest)
        return f"export/increment/{scope}/{date}@{w}"
    if manifest["mode"] == "full":
        return f"export/full/{date}@{w}"
    return f"export/workspace/{_scope(manifest)}/{date}@{w}"


def _scope(manifest: dict) -> str:
    ws = manifest["workspaces"]
    scope = ws[0] if len(ws) == 1 else f"{ws[0]}+{len(ws) - 1}"
    return re.sub(r"[^A-Za-z0-9._+-]", "-", scope)


# --------------------------------------------------------------------------- publish

@dataclass
class Published:
    repository_id: str
    root_commit: str
    commit: str
    parent: Optional[str]
    tag: str
    tag_object: str
    previous_tag: Optional[str] = None
    files: list = field(default_factory=list)
    repository_bytes: int = 0


def repository_bytes(work: Path) -> int:
    """Git's own measure of the repository's object store (loose and packed), in bytes."""
    out = git(["count-objects", "-v"], cwd=work).stdout
    vals = dict(line.split(": ", 1) for line in out.splitlines() if ": " in line)
    return (int(vals.get("size", 0)) + int(vals.get("size-pack", 0))) * 1024


def _identity(work: Path) -> Optional[dict]:
    p = work / IDENTITY_FILE
    return json.loads(p.read_text()) if p.exists() else None


def _skeleton(work: Path, schemas: dict) -> None:
    """The repository layout, written once and refreshed where it is derived."""
    for d in ("format/families", "catalogue", "governance", "mappings/jira-insight", "mappings/legacy-inventory",
              "mappings/foreign-schemas", CHECKPOINTS, "tools"):
        (work / d).mkdir(parents=True, exist_ok=True)
    for d in ("mappings/jira-insight", "mappings/legacy-inventory", "mappings/foreign-schemas"):
        keep = work / d / "README.md"
        if not keep.exists():
            keep.write_text(f"# {d}\n\nApproved mapping profiles (reviewed as code; see "
                            "docs/export-import-design.md §11). Nothing here is applied without review.\n")
    for name, body in schemas.items():
        p = work / "format" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n")
    (work / "VERSION").write_text(f"{REPOSITORY_LAYOUT}\nargus-archive/1\n")
    readme = work / "README.md"
    if not readme.exists():
        readme.write_text(README)
    tools = Path(__file__).parent / "repo_tools"
    for src in sorted(tools.iterdir()) if tools.exists() else []:
        if src.is_file() and not src.name.startswith("_"):
            dst = work / "tools" / src.name
            shutil.copyfile(src, dst)
            os.chmod(dst, 0o755)


def views(checkpoint: Path) -> dict[str, str]:
    """The reviewable YAML views, derived from a checkpoint's own chunks."""
    def rows(family: str) -> list[dict]:
        out = []
        for p in sorted(checkpoint.glob(f"*-{family}-*.ndjson.zst")):
            out += [r for _, r in chunks.read_chunk(p, family)]
        return out

    types = rows("types")
    attrs, units, enums = [], set(), []
    for t in types:
        for a in t.get("attributes") or []:
            if not isinstance(a, dict):
                continue
            attrs.append({"type": t["name"], "type_uid": t["uid"], **{k: a.get(k) for k in (
                "name", "kind", "type", "unit", "required", "unique", "restricted") if k in a}})
            if a.get("unit"):
                units.add(str(a["unit"]))
            if a.get("options"):
                enums.append({"type": t["name"], "attribute": a.get("name"), "options": a["options"]})
    policies = rows("policies")
    latest = max(policies, key=lambda p: p.get("activated_at") or "") if policies else None
    workflows = rows("workflows")
    documents = rows("documents")
    retention: dict[str, int] = {}
    for d in documents:
        retention[d.get("retention_class") or "unset"] = retention.get(d.get("retention_class") or "unset", 0) + 1
    reg_path = checkpoint / "relation-registry.json"
    reg = json.loads(reg_path.read_text()) if reg_path.exists() else {}
    dump = lambda v: yaml.safe_dump(v, sort_keys=True, allow_unicode=True, width=110)  # noqa: E731
    return {
        "catalogue/types.yaml": dump([{k: t.get(k) for k in ("uid", "name", "parent_schema_uid", "workspace_id",
                                                               "is_global", "is_concrete", "applies_to", "description")}
                                      for t in types]),
        "catalogue/attributes.yaml": dump(attrs),
        "catalogue/units.yaml": dump(sorted(units)),
        "catalogue/enumerations.yaml": dump(enums),
        "catalogue/relations.yaml": dump(reg),
        "governance/authority-policy.yaml": dump({"version": latest.get("version"), "body": latest.get("body"),
                                                  "activated_by": latest.get("activated_by"),
                                                  "activated_at": latest.get("activated_at")} if latest else {}),
        "governance/workflows.yaml": dump([{k: w.get(k) for k in sorted(w) if k not in ("created_at", "updated_at")}
                                           for w in workflows]),
        "governance/retention-policies.yaml": dump({"document_retention_classes": retention,
                                                    "legal_holds": "not modelled in ARGUS yet "
                                                                   "(docs/export-import-design.md §15)"}),
    }


def credentials_env(ssh_key: Optional[Path] = None, token_file: Optional[Path] = None,
                    askpass_dir: Optional[Path] = None, known_hosts: Optional[Path] = None) -> dict:
    """Git environment for one repository's deploy credential, read from a mounted secret: an SSH
    deploy key, or a token file answered through GIT_ASKPASS. Never written into a manifest, a
    repository or a log."""
    env: dict = {}
    if ssh_key is not None:
        # The server's host key is pinned: ARGUS_PORTABILITY_SSH_KNOWN_HOSTS names a known_hosts file
        # mounted with the deploy key (an unknown or changed host key is refused).
        # A repository registered in the web app brings its own, confirmed host keys.
        known = str(known_hosts) if known_hosts else os.environ.get("ARGUS_PORTABILITY_SSH_KNOWN_HOSTS")
        env["GIT_SSH_COMMAND"] = (f"ssh -i {ssh_key} -o IdentitiesOnly=yes -o BatchMode=yes "
                                  "-o StrictHostKeyChecking=yes"
                                  + (f" -o UserKnownHostsFile={known}" if known else ""))
    if token_file is not None:
        d = askpass_dir or token_file.parent
        script = d / "argus-git-askpass.sh"
        if not script.exists():
            d.mkdir(parents=True, exist_ok=True)
            script.write_text('#!/bin/sh\ncat "$ARGUS_GIT_TOKEN_FILE"\n')
            os.chmod(script, 0o700)
        env.update({"GIT_ASKPASS": str(script), "ARGUS_GIT_TOKEN_FILE": str(token_file)})
    return env


def publish(checkpoint: Path, manifest: dict, *, remote: str, work: Path, signer: Signer,
            schemas: dict, previous_tag: Optional[str] = None, credentials: Optional[dict] = None,
            artifacts: Optional[Path] = None) -> Published:
    """Commit and tag a checkpoint in the portability repository and push both. With `artifacts` (a directory
    store's root: sha256/<aa>/<digest>), the export's data files are committed too, under artifacts/, in the
    same signed commit; an artifact already there is the same file (named by its content) and stays."""
    work.parent.mkdir(parents=True, exist_ok=True)
    if not (work / ".git").exists():
        r = git(["clone", "--no-checkout", "--no-recurse-submodules", remote, str(work)], cwd=work.parent, check=False,
                env=credentials)
        if r.returncode != 0:
            raise GitError(f"cannot clone the portability repository: {r.stderr.strip()[:300]}", code="git_failed")
    git(["fetch", "--no-recurse-submodules", "--tags", "origin"], cwd=work, check=False, env=credentials)
    heads = git(["ls-remote", "--heads", "origin", "main"], cwd=work, env=credentials).stdout.strip()
    if heads:
        git(["checkout", "-B", "main", "origin/main"], cwd=work)
    else:
        git(["checkout", "--orphan", "main"], cwd=work, check=False)
    ident = _identity(work)
    if ident is None:
        ident = {"repository_id": str(uuid.uuid4()), "layout": REPOSITORY_LAYOUT,
                 "created_at": datetime.now(timezone.utc).isoformat(),
                 "created_by_instance": manifest["argus"]["instance_id"]}
        (work / IDENTITY_FILE).write_text(json.dumps(ident, indent=1, sort_keys=True) + "\n")
    dest = work / CHECKPOINTS / manifest["export_id"]
    if dest.exists():
        raise GitError(f"checkpoint {manifest['export_id']} is already in the repository; chunks are immutable",
                       code="immutable")
    _skeleton(work, schemas)
    dest.mkdir(parents=True)
    for name in git_files(manifest):
        if (checkpoint / name).exists():
            shutil.copyfile(checkpoint / name, dest / name)
    if not manifest.get("encryption"):
        for rel, body in views(checkpoint).items():
            (work / rel).write_text(body)
    if artifacts is not None and (artifacts / "sha256").is_dir():
        for src in (artifacts / "sha256").glob("*/*"):
            target = work / "artifacts" / "sha256" / src.parent.name / src.name
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, target)
    git(["add", "-A"], cwd=work)
    staged = [p for p in git(["diff", "--cached", "--name-only", "-z"], cwd=work).stdout.split("\0") if p]
    for rel in staged:
        path = work / rel
        # Artifacts were inspected for secrets when the export was generated, and are binary as often as not.
        if path.is_file() and not rel.endswith(".zst") and not rel.startswith("artifacts/"):
            found = secret_scan.scan_text(path.read_text(errors="replace"), rel)
            if found:
                git(["reset", "-q"], cwd=work, check=False)
                shutil.rmtree(dest, ignore_errors=True)
                raise GitError("a file to be committed looks like it holds a secret", code="secret_found",
                               detail={"findings": found})
    parent = git(["rev-parse", "--verify", "-q", "HEAD"], cwd=work, check=False).stdout.strip() or None
    tag = tag_name(manifest)
    msg = (f"ARGUS export {manifest['export_id']} ({manifest['mode']})\n\n"
           f"checkpoint: {manifest['watermark']['checkpoint_sequence']}\n"
           f"watermark-vector-sha256: {manifest['watermark']['vector_sha256']}\n"
           f"workspaces: {', '.join(manifest['workspaces'])}\n"
           f"manifest: {CHECKPOINTS}/{manifest['export_id']}/manifest.json\n"
           f"manifest-sha256: {manifest['_sha256']}\n")
    git(["commit", "-q", "-S", "-m", msg], cwd=work, signer=signer)
    commit = git(["rev-parse", "HEAD"], cwd=work).stdout.strip()
    git(["tag", "-s", tag, "-m", msg + f"export-id: {manifest['export_id']}\n"
         + (f"previous-tag: {previous_tag}\n" if previous_tag else ""), commit], cwd=work, signer=signer)
    r = git(["push", "--no-recurse-submodules", "origin", "HEAD:refs/heads/main", f"refs/tags/{tag}"], cwd=work,
            check=False, env=credentials)
    if r.returncode != 0:
        raise GitError(f"push refused: {r.stderr.strip()[:300]}", code="push_refused")
    # What this export wrote loose is packed now, so the local copy does not grow by a full copy every night
    # (services/storage_cleanup.py); a failure here never fails the export.
    from app.services.storage_cleanup import compact_after_publish
    compact_after_publish(work)
    root = git(["rev-list", "--max-parents=0", "HEAD"], cwd=work).stdout.split()[0]
    tag_object = git(["rev-parse", f"refs/tags/{tag}"], cwd=work).stdout.strip()
    return Published(ident["repository_id"], root, commit, parent, tag, tag_object, previous_tag, staged,
                     repository_bytes(work))


def init_bare(path: Path) -> str:
    """A bare repository (tests, and an institution's first set-up on a local server)."""
    path.mkdir(parents=True, exist_ok=True)
    git(["init", "--bare", "-q", "-b", "main", str(path)], cwd=path.parent)
    return str(path)


# --------------------------------------------------------------------------- quarantine

@dataclass
class Fetched:
    repository_id: str
    root_commit: str
    commit: str
    tag: Optional[str]
    tag_object: Optional[str]
    signer: str
    checkpoint: Path
    export_id: str
    tree: list
    lfs: list = field(default_factory=list)
    previous_tag: Optional[str] = None
    message: str = ""


def _tree(repo: Path, commit: str, limits: chunks.Limits) -> list[dict]:
    out = git(["ls-tree", "-r", "-l", "-z", "--full-tree", commit], cwd=repo, binary=True).stdout
    entries = []
    for raw in filter(None, out.split(b"\0")):
        meta, _, path_b = raw.partition(b"\t")
        mode, kind, sha, size = meta.decode().split()
        path = path_b.decode("utf-8", errors="strict")
        entries.append({"mode": mode, "type": kind, "sha": sha, "size": None if size == "-" else int(size),
                        "path": path})
    problems = []
    for e in entries:
        p = PurePosixPath(e["path"])
        if e["path"].startswith("/") or ".." in p.parts or any(x in ("", ".", ".git") for x in p.parts) \
                or "\\" in e["path"] or any(ord(c) < 32 for c in e["path"]):
            problems.append(f"unsafe path {e['path']!r}")
        if p.name == ".gitmodules" or e["mode"] == "160000" or e["type"] == "commit":
            problems.append(f"submodule {e['path']}")
        if e["mode"] == "120000":
            problems.append(f"symbolic link {e['path']}")
        if e["mode"] == "100755" and not e["path"].startswith(EXECUTABLE_ALLOWED):
            problems.append(f"executable payload {e['path']}")
        if e["size"] is not None and e["size"] > limits.max_file_bytes:
            problems.append(f"oversized object {e['path']} ({e['size']} bytes)")
    if problems:
        raise GitError("the repository holds content the importer refuses", code="unsafe_repository",
                       detail={"problems": problems[:50]})
    return entries


def fetch_into_quarantine(url: str, ref: str, qdir: Path, allowed_signers: Path, *,
                          limits: chunks.Limits = chunks.LIMITS, credentials_env: Optional[dict] = None) -> Fetched:
    """Fetch a signed tag (`refs/tags/export/...` or `export/...`) or a signed commit (40 hex digits)
    into a bare quarantine repository, verify it, and extract its checkpoint."""
    qdir.mkdir(parents=True, exist_ok=True)
    repo = qdir / "repo.git"
    if not repo.exists():
        git(["init", "--bare", "-q", str(repo)], cwd=qdir)
    is_commit = bool(re.fullmatch(r"[0-9a-f]{40}", ref))
    tag = None
    if not is_commit:
        tag = ref[len("refs/tags/"):] if ref.startswith("refs/tags/") else ref
        if ref.startswith("refs/heads/") or not tag.startswith("export/"):
            raise GitError(f"{ref!r} is not an export tag: import accepts a signed export tag or a signed "
                           "commit hash, never a branch", code="not_a_tag")
        r = git(["fetch", "-q", "--no-tags", "--no-recurse-submodules", url,
                 f"+refs/tags/{tag}:refs/tags/{tag}"], cwd=repo, check=False, env=credentials_env)
        if r.returncode != 0:
            raise GitError(f"cannot fetch {tag}: {r.stderr.strip()[:300]}", code="fetch_failed")
        if git(["cat-file", "-t", f"refs/tags/{tag}"], cwd=repo).stdout.strip() != "tag":
            raise GitError(f"{tag} is a lightweight tag: it carries no signature", code="unsigned")
        v = git(["verify-tag", "--raw", f"refs/tags/{tag}"], cwd=repo, check=False, allowed=allowed_signers)
        if v.returncode != 0:
            raise GitError(f"the signature of {tag} does not verify against the trusted keys", code="bad_signature",
                           detail={"git": (v.stderr or v.stdout).strip()[:300]})
        commit = git(["rev-parse", f"refs/tags/{tag}^{{commit}}"], cwd=repo).stdout.strip()
        tag_object = git(["rev-parse", f"refs/tags/{tag}"], cwd=repo).stdout.strip()
        message = git(["cat-file", "tag", tag_object], cwd=repo).stdout
    else:
        r = git(["fetch", "-q", "--no-tags", "--no-recurse-submodules", url, "+refs/tags/*:refs/remote-tags/*",
                 "+refs/heads/*:refs/remote-heads/*"], cwd=repo, check=False, env=credentials_env)
        if r.returncode != 0:
            raise GitError(f"cannot fetch: {r.stderr.strip()[:300]}", code="fetch_failed")
        if git(["cat-file", "-t", ref], cwd=repo, check=False).stdout.strip() != "commit":
            raise GitError(f"commit {ref} is not in the repository", code="missing_commit")
        commit, tag_object = ref, None
        message = git(["cat-file", "commit", commit], cwd=repo).stdout
    v = git(["verify-commit", "--raw", commit], cwd=repo, check=False, allowed=allowed_signers)
    if v.returncode != 0:
        raise GitError(f"commit {commit[:12]} is not signed by a trusted key", code="bad_signature")
    signer = _principal(v.stderr + v.stdout)
    tree = _tree(repo, commit, limits)
    paths = {e["path"]: e for e in tree}
    if IDENTITY_FILE not in paths:
        raise GitError("not an ARGUS portability repository (no identity file)", code="not_portability")
    ident = json.loads(git(["cat-file", "blob", paths[IDENTITY_FILE]["sha"]], cwd=repo).stdout)
    m = re.search(r"^export-id: (\S+)$", message, re.M) or re.search(
        rf"^manifest: {CHECKPOINTS}/([^/\s]+)/manifest\.json$", message, re.M)
    if not m:
        raise GitError("the tag or commit does not name its export", code="not_portability")
    export_id = m.group(1)
    if not SAFE_NAME.match(export_id):
        raise GitError(f"unsafe export id {export_id!r}", code="unsafe_repository")
    prefix = f"{CHECKPOINTS}/{export_id}/"
    out = qdir / "checkpoint"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir()
    lfs = []
    for path, e in paths.items():
        if not path.startswith(prefix):
            continue
        name = path[len(prefix):]
        if "/" in name or not SAFE_NAME.match(name):
            raise GitError(f"unexpected file {path!r} in the checkpoint", code="unsafe_repository")
        data = git(["cat-file", "blob", e["sha"]], cwd=repo, binary=True).stdout
        if data.startswith(LFS_POINTER):
            oid = re.search(rb"oid sha256:([0-9a-f]{64})", data)
            size = re.search(rb"size (\d+)", data)
            lfs.append({"file": name, "sha256": oid.group(1).decode() if oid else None,
                        "size": int(size.group(1)) if size else None})
        (out / name).write_bytes(data)
    if not (out / "manifest.json").exists():
        raise GitError(f"checkpoint {export_id} has no manifest in this commit", code="missing_chunk")
    root = git(["rev-list", "--max-parents=0", commit], cwd=repo).stdout.split()[0]
    prev = re.search(r"^previous-tag: (\S+)$", message, re.M)
    return Fetched(ident.get("repository_id", ""), root, commit, tag, tag_object, signer, out, export_id, tree,
                   lfs, prev.group(1) if prev else None, message)


def has_commit(qdir: Path, url: str, commit: str, descendant: str, credentials_env: Optional[dict] = None) -> bool:
    """Whether `commit` is in the repository and an ancestor of `descendant` (the chain is whole)."""
    repo = qdir / "repo.git"
    git(["fetch", "-q", "--no-tags", "--no-recurse-submodules", url, "+refs/heads/*:refs/remote-heads/*"], cwd=repo,
        check=False, env=credentials_env)
    if git(["cat-file", "-t", commit], cwd=repo, check=False).stdout.strip() != "commit":
        return False
    return git(["merge-base", "--is-ancestor", commit, descendant], cwd=repo, check=False).returncode == 0


def _principal(text: str) -> str:
    m = re.search(r'Good "git" signature for (\S+)', text)
    return m.group(1) if m else "trusted"


README = """# ARGUS portability repository

Signed, reviewable checkpoints of an ARGUS deployment (docs/export-import-design.md in ARGUS).

* `format/` — the JSON Schemas of `argus-archive/1`: manifest, record envelope, blob manifest, one per family.
* `catalogue/`, `governance/` — reviewable views of the catalogue, relation registry, authority policy,
  workflows and retention classes, derived from each checkpoint. Changing them here activates nothing.
* `mappings/` — approved mapping profiles for foreign and legacy schemas.
* `exports/checkpoints/<export-id>/` — one checkpoint: `manifest.json`, `blobs.manifest.ndjson`,
  `reconciliation.json`, `checksums.sha256`, `signature.json`, and the few small chunks stored in Git.
  Bulk chunks and blobs are artifacts named in the manifest by locator and digest. Immutable.
* `tools/` — `validate` and `inspect` verify a checkpoint without ARGUS; ARGUS never runs them.

An export is identified by its signed tag (`export/full/<date>@cp<n>-<vector hash>`,
`export/workspace/<workspace>/<date>@cp<n>-<vector hash>`) and the commit it names — never by a branch.
Data chunks and blobs are not in Git: the manifest and `blobs.manifest.ndjson` name each by SHA-256 and
locator; `tools/validate --artifacts store=/path` fetches and checks them.
Do not merge across checkpoints, rewrite history, force-push, or move a tag.
"""
