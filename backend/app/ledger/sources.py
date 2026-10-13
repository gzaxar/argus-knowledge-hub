"""Sources for the vertical slice: what a stream's bytes say, as claims.

* `epik8s-slice` — IOCs and devices of a values.yaml, with the inference rule
  `infer.vac.sip/1` (a vacuum channel named …SIP… is an ion-pump position).
  It creates **positions**, never physical assets (§4.2).
* `insight-fixture` — equipment exported from Jira Insight (migration source,
  §16): one object per entry, identified by its immutable objectId.
* `registry-fixture` — a registry export (the IT registry's equipment, ports
  and segments): records with attributes and relations.
* `resolved` — the resolver's own output (installation proposals from
  `asset:` URLs, rule `resolve.asset_url/1`), ingested like any other stream.

Every rule has a semantic id that is part of claim identity (§7.9).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Callable

import yaml
from sqlalchemy import String, cast, select
from sqlalchemy.orm import Session

from app.ledger import engine, rules
from app.ledger.engine import ParsedClaim, canonical
from app.models.ledger import Claim, ClaimEvent, JobRun, LedgerStream, SourceRevision, StreamHead

RULES = rules.RULES   # the catalogue lives in app.ledger.rules (§7.9)


@dataclass(frozen=True)
class Ruleset:
    """The semantic rule id each inference family runs, and its implementation."""
    rules: dict
    impl: dict

    def rule(self, family: str) -> str:
        return self.rules[family]

    def impl_of(self, rule_id: str) -> str:
        return self.impl.get(rule_id) or rules.latest_impl(rule_id)


@dataclass(frozen=True)
class Parser:
    version: str
    impl_version: str
    parse: Callable[[bytes, LedgerStream, Ruleset], list[ParsedClaim]]
    families: tuple = ()     # the inference families this parser runs

    def versions(self, ruleset: Ruleset) -> tuple[str, str]:
        """The parser version is part of the parse-skip key and names the
        semantic rules it ran; the implementation version names the code."""
        ids = [ruleset.rule(f) for f in self.families]
        return ("+".join([self.version, *ids]),
                ";".join([self.impl_version, *[f"{r}={ruleset.impl_of(r)}" for r in ids]]))


def _ioc_entries(iocs) -> list[dict]:
    if isinstance(iocs, dict):
        return [{"name": k, **v} if isinstance(v, dict) else {"name": k} for k, v in iocs.items()]
    return [e for e in iocs or [] if isinstance(e, dict)]


def _zones(value) -> list[str]:
    if value is None:
        return []
    return [str(z) for z in (value if isinstance(value, list) else [value])]


def normalize_address(host, port=None) -> str:
    """An Access Point address: a lower-case FQDN or IP, plus the port when
    the configuration gives one (§9.2)."""
    address = str(host).strip().lower().rstrip(".")
    return f"{address}:{port}" if port not in (None, "") else address


def _infer_vac(rule_id: str, impl: str, fac: str, ioc: dict, dev: dict, dref: str, dpath: str) -> list[ParsedClaim]:
    """The infer.vac.sip family. Each id is a different meaning (§7.9); each
    implementation of one id is the same meaning, possibly with a bug."""
    name = str(dev["name"])
    upper = name.upper()
    token = "SIP" if "SIP" in upper else "IONP" if "IONP" in upper else None
    devgroup = str(ioc.get("devgroup") or "").lower()
    if token is None:
        return []
    if rule_id == "infer.vac.sip/1":
        if "vac" not in devgroup and "vac" not in str(ioc.get("template") or "").lower():
            return []
    elif devgroup != "vac":
        return []
    if rule_id == "infer.vac.sip/3" and dev.get("channel") is None:
        return []
    position_class = "Ion Pump"
    if rule_id == "infer.vac.sip/2" and impl in ("2.0", "2.1") and token == "IONP":
        position_class = "Ion pump"   # the bug 2.2 fixes: same meaning, one output differs
    pref = f"infer:{fac}:pos:{name}"
    ev = {"devgroup": ioc.get("devgroup"), "template": ioc.get("template"), "name_token": token, "path": dpath}
    kw = {"method": "inferred", "rule_id": rule_id, "evidence": ev, "confidence": 0.9}
    return [
        ParsedClaim(pref, "exists", {"type": "Equipment Position", "key": f"{fac}:POS:{name}", "name": name}, **kw),
        ParsedClaim(pref, "attr:position_class", position_class, **kw),
        ParsedClaim(dref, "rel:acts on", {"ref": pref}, **kw),
    ]


def _infer_mag_ps(fac: str, ioc: dict, dev: dict, dref: str, dpath: str, endpoint_ref) -> list[ParsedClaim]:
    if str(ioc.get("devgroup") or "").lower() != "mag":
        return []
    name = f"{dev['name']}/PS"
    pref = f"infer:{fac}:pos:{name}"
    ev = {"devgroup": ioc.get("devgroup"), "path": dpath}
    kw = {"method": "inferred", "rule_id": "infer.mag.ps/1", "evidence": ev, "confidence": 0.9}
    out = [
        ParsedClaim(pref, "exists", {"type": "Equipment Position", "key": f"{fac}:POS:{name}", "name": name}, **kw),
        ParsedClaim(pref, "attr:position_class", "Power Supply", **kw),
        ParsedClaim(dref, "rel:acts on", {"ref": pref}, **kw),
    ]
    if endpoint_ref:
        out.append(ParsedClaim(endpoint_ref, "rel:assigned to", {"ref": pref}, **kw))
    return out


def parse_epik8s(content: bytes, stream: LedgerStream, ruleset: Ruleset) -> list[ParsedClaim]:
    values = yaml.safe_load(content) or {}
    fac = str(values.get("beamline") or stream.facility or "X").upper()
    iocs = _ioc_entries((values.get("epicsConfiguration") or {}).get("iocs"))
    vac_rule = ruleset.rule("infer.vac.sip")
    vac_impl = ruleset.impl_of(vac_rule)
    out: list[ParsedClaim] = []
    for ioc in iocs:
        name = str(ioc["name"])
        ioc_ref = f"epik8s:{fac}:ioc:{name}"
        path = f"epicsConfiguration.iocs.{name}"
        out.append(ParsedClaim(ioc_ref, "exists", {"type": "IOC", "key": f"{fac}:IOC:{name}", "name": name},
                               rule_id="epik8s.ioc/1", evidence={"path": path}))
        if ioc.get("template"):
            out.append(ParsedClaim(ioc_ref, "attr:template", str(ioc["template"]), rule_id="epik8s.ioc/1",
                                   evidence={"path": f"{path}.template"}))
        for i, dev in enumerate(ioc.get("devices") or []):
            if not isinstance(dev, dict) or not dev.get("name"):
                continue
            dname = str(dev["name"])
            dref = f"epik8s:{fac}:dev:{name}/{dname}"
            dpath = f"{path}.devices[{i}]"
            out.append(ParsedClaim(dref, "exists", {"type": "Control Device", "key": f"{fac}:DEV:{name}:{dname}",
                                                    "name": dname}, rule_id="epik8s.device/1",
                                   evidence={"path": dpath}))
            out.append(ParsedClaim(dref, "rel:provided by", {"ref": ioc_ref}, rule_id="epik8s.device/1",
                                   evidence={"path": dpath}))
            if dev.get("channel") is not None:
                out.append(ParsedClaim(dref, "attr:channel", dev["channel"], rule_id="epik8s.device/1",
                                       evidence={"path": f"{dpath}.channel"}))
            for zone in _zones(dev.get("zones", ioc.get("zones"))):
                out.append(ParsedClaim(dref, "attr:zones", zone, member=json.dumps(zone), rule_id="epik8s.device/1",
                                       evidence={"path": f"{dpath}.zones"}))
            if dev.get("asset"):
                out.append(ParsedClaim(dref, "attr:inventory_url", str(dev["asset"]), rule_id="epik8s.device/1",
                                       evidence={"path": f"{dpath}.asset"}))
            endpoint_ref = None
            if dev.get("host"):
                address = normalize_address(dev["host"], dev.get("port"))
                endpoint_ref = f"epik8s:{fac}:endpoint:{address}"
                path_ref = f"epik8s:{fac}:path:{name}/{dname}"
                ev = {"path": f"{dpath}.host"}
                out += [
                    ParsedClaim(endpoint_ref, "exists", {"type": "Access Point", "name": address},
                                rule_id="epik8s.endpoint/1", evidence=ev),
                    ParsedClaim(endpoint_ref, "attr:address", address, rule_id="epik8s.endpoint/1", evidence=ev),
                    ParsedClaim(path_ref, "exists", {"type": "Communication Path", "key": f"{fac}:PATH:{name}:{dname}",
                                                     "name": f"{name} → {address}"},
                                rule_id="epik8s.endpoint/1", evidence=ev),
                    ParsedClaim(path_ref, "rel:enters at", {"ref": endpoint_ref}, rule_id="epik8s.endpoint/1",
                                evidence=ev),
                ]
            out += _infer_vac(vac_rule, vac_impl, fac, ioc, dev, dref, dpath)
            out += _infer_mag_ps(fac, ioc, dev, dref, dpath, endpoint_ref)
    return out


def parse_insight(content: bytes, stream: LedgerStream, ruleset: Ruleset) -> list[ParsedClaim]:
    data = json.loads(content)
    out: list[ParsedClaim] = []
    for obj in data.get("objects", []):
        ref = f"insight:object:{obj['objectId']}"
        out.append(ParsedClaim(ref, "exists", {"type": obj["type"], "key": obj["key"], "name": obj.get("name")},
                               rule_id="insight.object/1", evidence={"objectId": obj["objectId"]}))
        for k, v in (obj.get("attributes") or {}).items():
            out.append(ParsedClaim(ref, f"attr:{k}", v, rule_id="insight.object/1",
                                   evidence={"objectId": obj["objectId"], "field": k}))
    return out


def parse_registry(content: bytes, stream: LedgerStream, ruleset: Ruleset) -> list[ParsedClaim]:
    """A registry export: records with their attributes and relations, each
    named by a ref that is stable across exports (the IT registry's ids)."""
    data = json.loads(content)
    out: list[ParsedClaim] = []
    for rec in data.get("records", []):
        ref = rec["ref"]
        kw = {"rule_id": "registry.record/1", "evidence": {"ref": ref}}
        out.append(ParsedClaim(ref, "exists", {"type": rec["type"], "key": rec.get("key"), "name": rec.get("name")},
                               **kw))
        for k, v in (rec.get("attributes") or {}).items():
            out.append(ParsedClaim(ref, f"attr:{k}", v, **kw))
        for rel, targets in (rec.get("relations") or {}).items():
            for t in targets if isinstance(targets, list) else [targets]:
                out.append(ParsedClaim(ref, f"rel:{rel}", {"ref": t}, **kw))
    return out


def parse_glpi(content: bytes, stream: LedgerStream, ruleset: Ruleset) -> list[ParsedClaim]:
    """A GLPI import (app/integrations/glpi): records in the registry form, each named by its GLPI identity
    (glpi:<instance>:<itemtype>:<id>), its link in GLPI as the evidence."""
    data = json.loads(content)
    out: list[ParsedClaim] = []
    for rec in data.get("records", []):
        ref = rec["ref"]
        evidence = {"ref": ref, "url": (rec.get("attributes") or {}).get("glpi_url")}
        kw = {"rule_id": "glpi.record/1", "evidence": evidence}
        out.append(ParsedClaim(ref, "exists", {"type": rec["type"], "key": rec.get("key"), "name": rec.get("name")},
                               **kw))
        out.append(ParsedClaim(ref, "name", rec.get("name"), **kw))
        for k, v in (rec.get("attributes") or {}).items():
            out.append(ParsedClaim(ref, f"attr:{k}", v, **kw))
        for rel, targets in (rec.get("relations") or {}).items():
            for t in targets if isinstance(targets, list) else [targets]:
                out.append(ParsedClaim(ref, f"rel:{rel}", {"ref": t}, **kw))
    return out


def parse_resolved(content: bytes, stream: LedgerStream, ruleset: Ruleset) -> list[ParsedClaim]:
    return [ParsedClaim(**c) for c in json.loads(content)]


PARSERS = {
    "epik8s-slice": Parser("epik8s-slice/2", "slice-impl/2", parse_epik8s, ("infer.vac.sip", "infer.mag.ps")),
    "insight-fixture": Parser("insight-fixture/1", "slice-impl/1", parse_insight),
    "registry-fixture": Parser("registry-fixture/1", "slice-impl/1", parse_registry),
    "glpi": Parser("glpi/1", "glpi-impl/1", parse_glpi),
    "resolved": Parser("resolved/1", "resolver/1", parse_resolved),
}

OBJECT_ID = re.compile(r"objectId=(\d+)")


def _published_claims(db: Session, stream_id: str) -> list[Claim]:
    head = db.get(StreamHead, stream_id)
    present = engine._presence(db, stream_id, head.published_number if head else 0)
    return [db.get(Claim, cid) for cid in present]


def workspaces_referencing(db: Session, changed: list) -> set[str]:
    """Workspaces whose configuration names one of these inventory objects in
    an `asset:` URL."""
    object_ids = {c.source_ref.rsplit(":", 1)[-1] for c in changed
                  if c is not None and c.source_ref.startswith("insight:object:")}
    out: set[str] = set()
    for oid in object_ids:
        for c in db.scalars(select(Claim).where(Claim.predicate == "attr:inventory_url",
                                                cast(Claim.value, String).like(f"%objectId={oid}%"))):
            stream = db.get(LedgerStream, c.stream_id)
            if stream is not None:
                out.add(stream.workspace_id)
    return out


def resolve_installations(db: Session, workspace_id: str) -> dict:
    """The resolve stage for one workspace (§8.4): an `asset:` URL on a device
    that names one inventory object, where the device acts on exactly one
    position, becomes an Installation *proposal*. Reruns whenever its inputs
    change (config claims, inventory bindings), even if no config bytes did."""
    streams = [s for s in db.scalars(select(LedgerStream).where(LedgerStream.workspace_id == workspace_id))
               if s.kind == "epik8s"]
    urls: dict[str, tuple[str, str]] = {}
    acts: dict[str, set] = {}
    for s in streams:
        for c in _published_claims(db, s.id):
            if c.predicate == "attr:inventory_url" and (m := OBJECT_ID.search(str(c.value))):
                urls[c.source_ref] = (m.group(1), c.claim_id)
            elif c.predicate == "rel:acts on" and c.polarity == "present":
                acts.setdefault(c.source_ref, set()).add(c.value["ref"])
    proposals: list[dict] = []
    inputs = []
    for dev_ref, (object_id, url_claim) in sorted(urls.items()):
        equipment_ref = f"insight:object:{object_id}"
        equipment_uid = engine.resolve_ref(db, equipment_ref)
        positions = sorted(acts.get(dev_ref, set()))
        inputs.append([dev_ref, object_id, url_claim, equipment_uid, positions])
        if equipment_uid is None or len(positions) != 1:
            continue
        pos_ref = positions[0]
        ref = f"resolve:inst:{pos_ref}|{equipment_ref}"
        appeared = db.scalar(select(ClaimEvent).where(ClaimEvent.claim_id == url_claim, ClaimEvent.kind == "appeared")
                             .order_by(ClaimEvent.seq).limit(1))
        rev = db.get(SourceRevision, appeared.revision_id) if appeared else None
        bound = (rev.observed_at if rev else engine.now()).isoformat()
        base = {"rule_id": "resolve.asset_url/1", "method": "resolved", "derived_from": [url_claim],
                "evidence": {"device": dev_ref, "objectId": object_id}, "confidence": 0.9}
        proposals += [
            {"source_ref": ref, "predicate": "exists", "value": {"type": "Installation"}, **base},
            {"source_ref": ref, "predicate": "rel:installed at", "value": {"ref": pos_ref}, **base},
            {"source_ref": ref, "predicate": "rel:installation of", "value": {"ref": equipment_ref}, **base},
            # The unit was there before these records began; the bound is the
            # first observation of the evidence, not an exact installation date.
            {"source_ref": ref, "predicate": "attr:valid_from",
             "value": {"kind": "before_records", "bound": bound}, **base},
        ]
    digest = hashlib.sha256(canonical(inputs).encode()).hexdigest()
    last = db.scalar(select(JobRun).where(JobRun.stage == "resolve", JobRun.scope == workspace_id)
                     .order_by(JobRun.id.desc()).limit(1))
    if last is not None and last.input_digest == digest:
        db.add(JobRun(stage="resolve", stage_version="resolver/1", scope=workspace_id, input_digest=digest,
                      status="skipped", counts={}, at=engine.now()))
        db.flush()
        return {"status": "skipped"}
    db.add(JobRun(stage="resolve", stage_version="resolver/1", scope=workspace_id, input_digest=digest,
                  status="ran", counts={"proposals": len(proposals) // 4}, at=engine.now()))
    db.flush()
    stream = engine.register_stream(db, f"resolve:{workspace_id}", workspace_id, "resolver",
                                    may_create=["Installation"])
    engine.ingest(db, stream.id, revision=digest[:12], content=canonical(proposals).encode(),
                  observed_at=engine.now(), parser="resolved", cause="resolve")
    return {"status": "ran", "proposals": len(proposals) // 4}
