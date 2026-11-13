"""The reviewed questions Ask ARGUS is measured on, and the synthetic workspaces they are asked in.

A dataset is a directory (``data/v1``): ``cases.yaml`` (the questions and what a right answer must and must not
contain), ``fixtures/*.yaml`` (the workspaces), ``human_labels.yaml`` (answers graded by domain experts, to
calibrate a judge model). Everything is validated on load, and hashed, so a report says exactly which questions
and which records it measured.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ask_eval import DATASET_VERSION

DATA = Path(__file__).parent / "data"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Role(_Strict):
    """Who is asking: the restricted classes they may read and whether Ask may propose changes for them."""
    description: str
    grants: list[str] = Field(default_factory=list)
    can_propose: bool = False


class Fact(_Strict):
    """A conclusion the answer must reach. Met when any pattern matches the answer (case, accents and dashes
    ignored); ``{ref:X}`` in a pattern is the actual key of fixture record X in this run."""
    id: str
    any: list[str] = Field(min_length=1)
    note: Optional[str] = None


class Forbidden(_Strict):
    """A claim the answer must not make: an invention, a contradiction, an instruction it obeyed."""
    id: str
    pattern: str
    reason: str


class Proposal(_Strict):
    """A request to change something. Ask may only propose (never claim to have changed a record); for a person
    who may not change records it must say so instead."""
    expected: Literal["propose", "decline"]
    tools: list[str] = Field(default_factory=list)


class Message(_Strict):
    role: Literal["user", "assistant"]
    content: str


class Attachment(_Strict):
    name: str
    text: str


class Case(_Strict):
    id: str
    language: Literal["en", "it"]
    domain: Literal["it", "accelerator", "core", "help"]
    severity: Literal["critical", "high", "medium", "low"]
    tags: list[str] = Field(default_factory=list)
    fixture: str
    role: str = "reader"
    question: str
    history: list[Message] = Field(default_factory=list)
    attachment: Optional[Attachment] = None
    required_facts: list[Fact] = Field(default_factory=list)
    # Fixture identifiers (uid, key or document code) of the records the answer rests on.
    expected_sources: list[str] = Field(default_factory=list)
    # Passages: words that must appear in what the lookups returned (a document's section, a ticket's comment).
    expected_passages: list[str] = Field(default_factory=list)
    forbidden_claims: list[Forbidden] = Field(default_factory=list)
    # The right answer is that the records do not establish it.
    expect_insufficient: bool = False
    # Never in the answer nor in what the tools returned to the model: a restricted record for a person without
    # its class, another workspace's private record. A hard failure.
    must_not_reveal: list[str] = Field(default_factory=list)
    proposal: Optional[Proposal] = None
    # False: the public report keeps this case's scores but not its question, answer or evidence text.
    publish: bool = True
    note: Optional[str] = None

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", v):
            raise ValueError("a case id is lowercase letters, digits and dashes")
        return v

    @model_validator(mode="after")
    def _checkable(self):
        if not (self.required_facts or self.expect_insufficient or self.must_not_reveal or self.proposal
                or self.forbidden_claims):
            raise ValueError(f"{self.id}: nothing to check — give facts, forbidden claims, a proposal or "
                             "expect_insufficient")
        for f in self.forbidden_claims:
            re.compile(f.pattern)
        for f in self.required_facts:
            for p in f.any:
                re.compile(re.sub(r"\{ref:[^}]+\}", "X", p))
        return self


class FixtureWorkspace(_Strict):
    """One workspace of a fixture: a demo bundle applied, records added, or both."""
    suffix: str                                   # the workspace is askeval-<run>-<fixture>-<suffix>
    name: str
    bundle: Optional[str] = None                  # demo_workspaces/<bundle>
    is_global: bool = False
    allow_confidential: bool = False              # the workspace's AI setting
    records: dict = Field(default_factory=dict)


class Fixture(_Strict):
    id: str
    description: str
    workspaces: list[FixtureWorkspace] = Field(min_length=1)   # the first is the one questions are asked in


class Dataset(_Strict):
    version: str
    description: str
    roles: dict[str, Role]
    cases: list[Case]
    fixtures: dict[str, Fixture] = Field(default_factory=dict)
    human_labels: list[dict] = Field(default_factory=list)
    sha256: str = ""
    fixture_sha256: dict[str, str] = Field(default_factory=dict)

    def case(self, case_id: str) -> Case:
        return next(c for c in self.cases if c.id == case_id)


def _hash_files(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.name.encode())
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _bundle_hash(name: str) -> str:
    manifest = Path(__file__).resolve().parents[2] / "demo_workspaces" / name / "manifest.json"
    return hashlib.sha256(manifest.read_bytes()).hexdigest() if manifest.exists() else "missing"


def load(version: str = DATASET_VERSION, root: Optional[Path] = None) -> Dataset:
    """The dataset, validated: unique case ids, every case's fixture and role defined, and its hashes."""
    base = (root or DATA) / version
    raw = yaml.safe_load((base / "cases.yaml").read_text())
    fixtures = {}
    fixture_files = sorted((base / "fixtures").glob("*.yaml"))
    for f in fixture_files:
        fx = Fixture(**yaml.safe_load(f.read_text()))
        if fx.id != f.stem:
            raise ValueError(f"{f.name}: its id is {fx.id!r}; a fixture's file is named after its id")
        fixtures[fx.id] = fx
    labels_file = base / "human_labels.yaml"
    labels = (yaml.safe_load(labels_file.read_text()) or {}).get("labels", []) if labels_file.exists() else []
    ds = Dataset(**raw, fixtures=fixtures, human_labels=labels)
    seen = set()
    for c in ds.cases:
        if c.id in seen:
            raise ValueError(f"case id {c.id} is used twice")
        seen.add(c.id)
        if c.fixture not in ds.fixtures:
            raise ValueError(f"{c.id}: no fixture {c.fixture!r}")
        if c.role not in ds.roles:
            raise ValueError(f"{c.id}: no role {c.role!r}")
    ds.sha256 = _hash_files([base / "cases.yaml", *([labels_file] if labels_file.exists() else [])])
    for fx_id, fx in ds.fixtures.items():
        h = hashlib.sha256(_hash_files([base / "fixtures" / f"{fx_id}.yaml"]).encode())
        for w in fx.workspaces:
            if w.bundle:
                h.update(_bundle_hash(w.bundle).encode())
        ds.fixture_sha256[fx_id] = h.hexdigest()
    return ds
