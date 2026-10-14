"""The rule catalogue (asset-model-revision §7.9).

A **semantic rule id** names a meaning and never changes; the `/n` suffix is
part of it. An **implementation version** is the code that ran the rule. It
is recorded on claim events and job runs, never in claim identity. So:

* a refactor with identical output writes no claim events;
* a bug fix within the declared meaning writes `disappeared`/`appeared` for
  the outputs it changes, under the same rule id;
* a change of meaning needs a new rule id, and every output becomes a new
  claim.

Each rule declares its output signature. `rules.lock.json`, committed next
to this file, pins the signature hash of every rule id; `check_catalogue()`
fails when a signature changes without a new id (the CI check), and
`python -m app.ledger.rules --lock` adds the ids that are new, never
rewriting an existing one.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Optional

LOCK_PATH = Path(__file__).with_name("rules.lock.json")

RULES: dict[str, dict] = {
    # AI Intake operations (asset-model-revision §23.8): what a model may propose from a description.
    "ai.asset.describe/1": {
        "family": "ai.asset.describe",
        "meaning": "fields of an asset read by a model from a person's description or photograph",
        "signature": {"outputs": ["name", "type", "attr:*"], "methods": ["ai_extracted", "ai_classified"]},
        "impl": ["1"],
    },
    "ai.ticket.describe/1": {
        "family": "ai.ticket.describe",
        "meaning": "ticket fields read by a model from a person's report; causes only as hypotheses",
        "signature": {"outputs": ["title", "type", "attr:*"], "methods": ["ai_extracted", "ai_classified"]},
        "impl": ["1"],
    },
    "ai.document.describe/1": {
        "family": "ai.document.describe",
        "meaning": "document title, type, summary and keywords read by a model from a person's text",
        "signature": {"outputs": ["title", "type", "summary", "keywords"],
                      "methods": ["ai_extracted", "ai_classified"]},
        "impl": ["1"],
    },
    "epik8s.ioc/1": {
        "family": "epik8s.ioc",
        "meaning": "an IOC entry is a control-plane IOC record",
        "signature": {"outputs": ["exists", "attr:template"], "subject_types": ["IOC"]},
        "impl": ["1"],
    },
    "epik8s.device/1": {
        "family": "epik8s.device",
        "meaning": "a device of an IOC is a Control Device",
        "signature": {"outputs": ["exists", "attr:channel", "attr:zones", "attr:inventory_url", "rel:provided by"],
                      "subject_types": ["Control Device"], "target_types": {"rel:provided by": ["IOC"]}},
        "impl": ["1"],
    },
    "epik8s.endpoint/1": {
        "family": "epik8s.endpoint",
        "meaning": "a device's host is an Access Point, reached from its IOC through a Communication Path",
        "signature": {"outputs": ["exists", "attr:address", "rel:enters at"],
                      "subject_types": ["Access Point", "Communication Path"],
                      "target_types": {"rel:enters at": ["Access Point"]}},
        "impl": ["1"],
    },
    "infer.vac.sip/1": {
        "family": "infer.vac.sip",
        "meaning": "a vacuum channel whose name contains SIP or IONP denotes an Equipment Position of class "
                   "Ion Pump, which the channel acts on",
        "signature": {"outputs": ["exists", "attr:position_class", "rel:acts on"],
                      "subject_types": ["Equipment Position"], "value_domain": {"attr:position_class": ["Ion Pump"]},
                      "conditions": "devgroup or template names vac; device name has SIP or IONP"},
        "impl": ["1"],
    },
    "infer.vac.sip/2": {
        "family": "infer.vac.sip",
        "meaning": "a channel of a vacuum IOC (devgroup vac) whose name contains SIP or IONP denotes an "
                   "Equipment Position of class Ion Pump, which the channel acts on",
        "signature": {"outputs": ["exists", "attr:position_class", "rel:acts on"],
                      "subject_types": ["Equipment Position"], "value_domain": {"attr:position_class": ["Ion Pump"]},
                      "conditions": "devgroup is vac; device name has SIP or IONP"},
        "supersedes": "infer.vac.sip/1",
        "carries_rejections": False,
        "impl": ["2.0", "2.1", "2.2"],
    },
    "infer.vac.sip/3": {
        "family": "infer.vac.sip",
        "meaning": "a channel of a vacuum IOC with a channel number whose name contains SIP or IONP denotes an "
                   "Equipment Position of class Ion Pump, which the channel acts on",
        "signature": {"outputs": ["exists", "attr:position_class", "rel:acts on"],
                      "subject_types": ["Equipment Position"], "value_domain": {"attr:position_class": ["Ion Pump"]},
                      "conditions": "devgroup is vac; device has a channel; device name has SIP or IONP"},
        "supersedes": "infer.vac.sip/2",
        "carries_rejections": True,
        "impl": ["3.0"],
    },
    "infer.mag.ps/1": {
        "family": "infer.mag.ps",
        "meaning": "a device of a magnet IOC (devgroup mag) denotes the power-supply position of that magnet, "
                   "which the device acts on; the device's host is assigned to that position",
        "signature": {"outputs": ["exists", "attr:position_class", "rel:acts on", "rel:assigned to"],
                      "subject_types": ["Equipment Position", "Access Point"],
                      "value_domain": {"attr:position_class": ["Power Supply"]}},
        "impl": ["1"],
    },
    "insight.object/1": {
        "family": "insight.object",
        "meaning": "an Insight object is a piece of equipment",
        "signature": {"outputs": ["exists", "attr:*"]},
        "impl": ["1"],
    },
    "registry.record/1": {
        "family": "registry.record",
        "meaning": "a record of a registry export (IT equipment, ports, segments) is that record, with the "
                   "attributes and relations it lists",
        "signature": {"outputs": ["exists", "attr:*", "rel:*"]},
        "impl": ["1"],
    },
    "glpi.record/1": {
        "family": "glpi.record",
        "meaning": "a GLPI item, by its GLPI identity, is an ARGUS record with the fields the GLPI mapping gives it",
        "signature": {"outputs": ["exists", "name", "attr:*", "rel:*"]},
        "impl": ["1"],
    },
    "glpi.reference/1": {
        "family": "glpi.reference",
        "meaning": "a GLPI item's link to another (location, product, supplier) is a reference field naming the "
                   "ARGUS record that other item became",
        "signature": {"outputs": ["attr:*"], "methods": ["stated"]},
        "impl": ["1"],
    },
    "bind.control.tag/1": {
        "family": "bind.control.tag",
        "meaning": "a control channel acts on the one physical unit whose tag has the same zone, function code "
                   "and number (FI33TRB01 and FI33-V-PMP-TRB-001)",
        "signature": {"outputs": ["rel:acts on"], "subject_types": ["Control Device"]},
        "impl": ["1"],
    },
    "bind.control.host/1": {
        "family": "bind.control.host",
        "meaning": "a control channel, or an Access Point of an Ethernet instrument, is the one physical unit "
                   "that answers to its network address",
        "signature": {"outputs": ["rel:acts on", "rel:implemented by"],
                      "subject_types": ["Control Device", "Access Point"]},
        "impl": ["1"],
    },
    "ai.epik8s.classify/1": {
        "family": "ai.epik8s.classify",
        "meaning": "the AI proposes which kind of equipment a control channel no rule recognised drives: a unit "
                   "of that catalogue type exists, and the channel acts on it",
        "signature": {"outputs": ["exists", "name", "attr:description", "rel:acts on"],
                      "subject_types": ["Control Device"]},
        "impl": ["1"],
    },
    "beam-model.canonical/1": {
        "family": "beam-model.canonical",
        "meaning": "a canonical beam model (docs/beam-model.md) states its beam systems, beams, paths, elements, "
                   "their topology, the observables its diagnostics observe and its model datasets",
        "signature": {"outputs": ["exists", "name", "attr:*", "rel:*"]},
        "impl": ["1"],
    },
    "beam-model.bind-by-name/1": {
        "family": "beam-model.bind-by-name",
        "meaning": "a physical asset whose name or tag names exactly one beam element of its workspace is proposed "
                   "as installed at that position; a person confirms it, a name alone never does",
        "signature": {"outputs": ["exists", "rel:installed at", "rel:installation of", "attr:valid_from"],
                      "subject_types": ["Installation"]},
        "impl": ["1"],
    },
    "resolve.asset_url/1": {
        "family": "resolve.asset_url",
        "meaning": "a device's asset: URL naming one inventory object, on a device acting on exactly one "
                   "position, proposes an Installation of that object there",
        "signature": {"outputs": ["exists", "rel:installed at", "rel:installation of", "attr:valid_from"],
                      "subject_types": ["Installation"]},
        "impl": ["1"],
    },
}

# What runs when nothing else is activated.
DEFAULT_RULESET = {"infer.vac.sip": "infer.vac.sip/1", "infer.mag.ps": "infer.mag.ps/1"}


def latest_impl(rule_id: str) -> str:
    return RULES[rule_id]["impl"][-1]


def signature_hash(rule_id: str, catalogue: Optional[dict] = None) -> str:
    rule = (catalogue or RULES)[rule_id]
    payload = json.dumps(rule["signature"], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def load_lock() -> dict:
    return json.loads(LOCK_PATH.read_text()) if LOCK_PATH.exists() else {}


def check_catalogue(catalogue: Optional[dict] = None, lock: Optional[dict] = None) -> list[str]:
    """The CI check (I-RULE-1): every rule id keeps the signature it was
    locked with, every rule is locked, and every `supersedes` names a rule."""
    catalogue = catalogue if catalogue is not None else RULES
    lock = lock if lock is not None else load_lock()
    errors = []
    for rule_id, rule in sorted(catalogue.items()):
        if rule_id.rsplit("/", 1)[0] != rule["family"]:
            errors.append(f"{rule_id}: the id must be <family>/<n>")
        if rule_id not in lock:
            errors.append(f"{rule_id}: not in rules.lock.json (run python -m app.ledger.rules --lock)")
        elif lock[rule_id] != signature_hash(rule_id, catalogue):
            errors.append(f"{rule_id}: output signature changed without a new rule id")
        if rule.get("supersedes") and rule["supersedes"] not in catalogue:
            errors.append(f"{rule_id}: supersedes unknown rule {rule['supersedes']}")
    for rule_id in sorted(set(lock) - set(catalogue)):
        errors.append(f"{rule_id}: locked but missing from the catalogue (a rule id is never deleted)")
    return errors


def lock_new_rules() -> list[str]:
    lock = load_lock()
    added = [r for r in sorted(RULES) if r not in lock]
    for r in added:
        lock[r] = signature_hash(r)
    LOCK_PATH.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")
    return added


if __name__ == "__main__":
    if "--lock" in sys.argv:
        print("locked:", ", ".join(lock_new_rules()) or "nothing new")
    problems = check_catalogue()
    for p in problems:
        print("error:", p)
    sys.exit(1 if problems else 0)
