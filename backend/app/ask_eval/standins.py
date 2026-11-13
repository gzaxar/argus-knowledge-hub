"""Deterministic stand-ins for a chat model: the whole evaluation runs, end to end, without a model server.

They answer through the real Ask loop — the real tools are called, in the real fixtures, with the real
permissions — but the model's side of the conversation is scripted from the graded answers in
``human_labels.yaml``:

* ``standin:reference`` looks up every record its answer rests on (the case's expected sources and every code it
  will cite), proposes a change when the case asks for one and the role allows it, then gives the passing answer;
* ``standin:careless`` looks nothing up and gives the failing answer when there is one (else the passing one).

They exist to test the runner, the scoring and the reports in CI, and to produce the sample report. They are not
models and their numbers say nothing about any model.
"""
from __future__ import annotations

import contextlib
import json
import re
from typing import Optional

from app.ask_eval.dataset import Case, Dataset
from app.ask_eval.scoring import CODE

PREFIX = "standin:"
PERSONAS = ("reference", "careless")


class StandIn:
    def __init__(self, persona: str, dataset: Dataset):
        if persona not in PERSONAS:
            raise ValueError(f"no stand-in {persona!r}")
        self.persona, self.dataset = persona, dataset

    def endpoint(self):
        from app.services.llm import Endpoint
        return Endpoint(base_url=f"http://{self.persona}.standin.invalid/v1", model=f"{PREFIX}{self.persona}")

    # ---- which case is being asked
    def _case(self, messages: list[dict]) -> Optional[Case]:
        from app.ask_eval.runner import CURRENT_CASE
        if CURRENT_CASE.get():
            return self.dataset.case(CURRENT_CASE.get())
        users = [m for m in messages if m.get("role") == "user"]
        question = str(users[-1]["content"]) if users else ""
        for c in self.dataset.cases:
            if question.startswith(c.question.strip()):
                return c
        return None

    def _answers(self, case: Case) -> tuple[Optional[str], Optional[str]]:
        good = next((lb["answer"] for lb in self.dataset.human_labels
                     if lb["case"] == case.id and lb["grade"] == "pass"), None)
        bad = next((lb["answer"] for lb in self.dataset.human_labels
                    if lb["case"] == case.id and lb["grade"] == "fail"), None)
        return good, bad

    # ---- one model turn
    def converse(self, messages: list[dict], tools: Optional[list] = None) -> dict:
        case = self._case(messages)
        if case is None:
            return {"role": "assistant", "content": "I cannot tell which question this is."}
        good, bad = self._answers(case)
        if self.persona == "careless":
            return {"role": "assistant", "content": (bad or good or "I do not know.").strip()}

        offered = {t["function"]["name"] for t in tools or []}
        done = [m for m in messages if m.get("role") == "tool"]
        asked = {c["function"]["name"] + json.dumps(json.loads(c["function"]["arguments"]), sort_keys=True)
                 for m in messages if m.get("role") == "assistant" for c in (m.get("tool_calls") or [])}
        answer = (good or "").strip()
        wanted = list(dict.fromkeys(case.expected_sources + CODE.findall(answer)))
        # Round 1: open each record as an object; round 2: what was not an object, as a document; round 3: a ticket.
        plan: list[tuple[str, dict]] = []
        if not done:
            plan = [("get_object", {"uid_or_key": w}) for w in wanted]
            if case.domain == "help":
                plan = [("search_help", {"query": case.question})]
        else:
            missing = [w for w in wanted if not _found(messages, "get_object", w)]
            for w in missing:
                if not _tried(asked, "get_document", {"uid_or_code": w}):
                    plan.append(("get_document", {"uid_or_code": w}))
                elif not _found(messages, "get_document", w) and not _tried(asked, "get_ticket", {"uid": w}):
                    plan.append(("get_ticket", {"uid": w}))
        if (not plan and case.proposal and case.proposal.expected == "propose"
                and "propose_update_record" in offered and not any("propose_" in a for a in asked)):
            name = re.search(r'"([^"]+)"', case.question)
            plan = [("propose_update_record", {"record": wanted[0] if wanted else "NF-AP-LIB-03",
                                               "name": name.group(1) if name else "renamed",
                                               "reason": "asked by the person"})]
        plan = [(n, a) for n, a in plan if n in offered]
        if plan:
            return {"role": "assistant", "content": "", "tool_calls": [
                {"id": f"call-{len(done)}-{i}", "type": "function",
                 "function": {"name": n, "arguments": json.dumps(a)}} for i, (n, a) in enumerate(plan)]}
        return {"role": "assistant", "content": answer or "The records do not say."}


def _tried(asked: set, name: str, args: dict) -> bool:
    return name + json.dumps(args, sort_keys=True) in asked


def _found(messages: list[dict], tool: str, ident: str) -> bool:
    """Whether a lookup of `ident` with `tool` found it, from the tool results in the conversation."""
    calls = {}
    for m in messages:
        for c in (m.get("tool_calls") or []) if m.get("role") == "assistant" else []:
            calls[c["id"]] = (c["function"]["name"], json.loads(c["function"]["arguments"]))
    for m in messages:
        if m.get("role") != "tool":
            continue
        name, args = calls.get(m.get("tool_call_id"), ("", {}))
        if name == tool and ident in args.values():
            try:
                return json.loads(m.get("content") or "{}").get("found") is True
            except ValueError:
                return False
    return False


@contextlib.contextmanager
def installed(dataset: Dataset):
    """Ask's model calls answered by the stand-ins for endpoints whose model is standin:<persona>; every other
    endpoint still goes to its server."""
    from app.services import ask as ask_module
    real = ask_module.converse
    personas = {p: StandIn(p, dataset) for p in PERSONAS}

    def converse(endpoint, messages, tools=None):
        if str(endpoint.model).startswith(PREFIX):
            from app.services import usage
            reply = personas[endpoint.model[len(PREFIX):]].converse(messages, tools)
            usage.note_llm(endpoint.model, "chat", prompt_text=json.dumps(messages)[:200000],
                           completion_text=reply.get("content") or json.dumps(reply.get("tool_calls") or []))
            usage.note_served(endpoint.model)
            return reply
        return real(endpoint, messages, tools=tools)

    ask_module.converse = converse
    try:
        yield personas
    finally:
        ask_module.converse = real


def factory(dataset: Dataset):
    personas = {p: StandIn(p, dataset) for p in PERSONAS}

    def make(model: str):
        persona = model[len(PREFIX):] if model.startswith(PREFIX) else model
        return personas[persona].endpoint()
    return make
