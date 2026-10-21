"""Answering a question from the hub's own knowledge.

This is the test ARGUS has to pass. The project's claim is that structured
knowledge answers questions a pile of documents cannot — "what has gone
wrong with this magnet before, and which procedure covers it" — and the
only honest way to find out is to let somebody ask, in their own words,
and watch which records the answer actually came from.

So the tool calls are not an implementation detail to hide. They are the
output: every call and every result is returned alongside the answer, and
a question that produced a confident paragraph from no tool calls at all
is a failure, however well it reads.

The tools are the MCP ones, called in process. The same eight tools an
external assistant gets, so what is learned here is true there too.
"""
import json
import re
import time
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.services.llm import Endpoint, LLMError, converse, converse_stream
from app.services.mcp_tools import BY_NAME, catalogue

# Enough hops for search → open → traverse, and a stop before a confused
# model spends a workspace's quota going in circles.
MAX_ROUNDS = 8
# What comes back from a tool can be long; the model does not need all of
# it and the context window certainly does not.
MAX_TOOL_CHARS = 12000

# Reasoning models — minimax-m27, which is what LNF points at — narrate
# their working in a <think> block and then answer. The narration is not
# the answer and must not be shown as one.
THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S | re.I)
UNCLOSED_THINK = re.compile(r"<think>.*$", re.S | re.I)


def _answer_of(message: dict) -> str:
    """The answer a model meant to give, without its thinking aloud."""
    text = THINK_BLOCK.sub("", message.get("content") or "")
    # An unclosed block means it ran out of budget mid-thought; what
    # follows is nothing, and showing the monologue instead of saying so
    # is how a page passes off working-out as an answer.
    if UNCLOSED_THINK.search(text):
        text = UNCLOSED_THINK.sub("", text)
    return text.strip()

SYSTEM = (
    "You answer questions about a particle accelerator's equipment, the work done on "
    "it, and its documentation, using only the tools provided.\n\n"
    "Work from the records, never from what you know about accelerators in general. "
    "Look things up before answering — a question you think you can answer without a "
    "tool call is a question you are about to answer about some other laboratory.\n"
    "Names here are codes: equipment is called things like FI4-B-CAM-VIS-001, and the "
    "word somebody uses ('camera', 'quadrupole') is usually the type rather than the "
    "name. If a search finds nothing, try the word as a type, or a shorter fragment, "
    "before concluding there is none.\n"
    "A kind of equipment is often several types, organised in a tree, and none of them may "
    "carry the word used in the question. When you are not sure which types a word means, "
    "call list_types (with the word, or with nothing to see every type), choose the types "
    "whose descriptions match, and search_objects with types=[...]. For a question about "
    "what there is or how many, give the total and the count per type from by_type, not "
    "just the objects listed. List at most 40 records; when there are more, say how many "
    "more there are rather than stopping part way.\n"
    "For what is written rather than what exists — how to do something, what a manual or "
    "datasheet says, what went wrong before and how it was fixed — use search_knowledge: it "
    "finds passages by meaning, in any language. Cite a passage by the code or key of its "
    "record (in `record`), with its title and its page or section when it has one.\n"
    "For anything that spans records — what has failed before, what a procedure "
    "covers, what depends on what — use graph_neighbours. Searching text alone will "
    "miss it, because the answer is in no single record.\n\n"
    "For how to use ARGUS itself — how do I create a workspace, import, export, give a role, what does a "
    "screen do — use search_help, then read_help for the whole topic, and answer from the guide: give the "
    "steps in order with the exact names of the pages and buttons it uses, and offer to go through them one "
    "at a time. Do not make up menus or buttons the guide does not name.\n\n"
    "For building, configuring or debugging an EPICS IOC (ibek, ibek-templates, a driver, a beamline "
    "values.yaml entry), use the ioc_* tools: ioc_search, then the module, template or example; check an entry "
    "with ioc_render before proposing it, and say what its errors mean. Never propose an entity type, parameter "
    "or template the catalogue does not have, except in a new module ioc_scaffold_module writes for hardware "
    "with no EPICS support yet (ask for its commands first; never invent them).\n\n"
    "Cite what you used: write the key or code of each record the answer rests on, in backticks "
    "exactly as the records give it (`PROC-012`, `SPARC:VAC:IP-02`), which makes it a link to the record. "
    "Never invent a key, a code or a value; if the records do not say, say that they "
    "do not, and say what you looked at. An answer that sounds right and is not in "
    "the records is worse than no answer, because somebody will act on it."
)


def _tool_specs() -> list[dict]:
    """The MCP catalogue in the shape the chat API wants."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["inputSchema"],
            },
        }
        for tool in catalogue()
    ]


def _run_tool(db: Session, workspace_id: str, name: str, arguments: dict) -> tuple[str, Optional[str]]:
    """The tool's result as text, and an error message if it failed.

    A failing tool is told to the model rather than raised: a wrong
    argument is something it can correct on the next turn, and killing the
    whole question over one bad call wastes the rounds already spent.
    """
    tool = BY_NAME.get(name)
    if tool is None:
        return f"No such tool: {name}", f"No such tool: {name}"
    allowed = {
        key: value
        for key, value in (arguments or {}).items()
        if key in tool["inputSchema"].get("properties", {})
    }
    try:
        result = tool["handler"](db, workspace_id, **allowed)
    except Exception as e:  # noqa: BLE001 — reported, not swallowed
        message = f"{type(e).__name__}: {e}"
        return message, message
    return json.dumps(result, ensure_ascii=False, default=str)[:MAX_TOOL_CHARS], None


def _arguments_of(call: dict) -> dict:
    raw = (call.get("function") or {}).get("arguments")
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except ValueError:
        return {}


# Earlier turns of a conversation sent with a follow-up: enough for "and which of those are in AC1?",
# not so much that a long chat crowds out the records looked up for this question.
HISTORY_TURNS = 6
HISTORY_CHARS = 4000


def _history(history: Optional[list]) -> list[dict]:
    """A conversation's earlier questions and answers, newest last, trimmed."""
    turns = [m for m in (history or []) if m.get("role") in ("user", "assistant") and m.get("content")]
    return [{"role": m["role"], "content": str(m["content"])[:HISTORY_CHARS]}
            for m in turns[-2 * HISTORY_TURNS:]]


def _summary(name: str, text: str, error: Optional[str]) -> str:
    """One line for a lookup's result, for the person watching it run."""
    if error:
        return error
    try:
        data = json.loads(text)
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    if data.get("available") is False:
        return "not available here"
    if data.get("body") and data.get("slug"):
        return "1 guide topic"
    if isinstance(data.get("results"), list):
        return f"{len(data['results'])} passages"
    if isinstance(data.get("total"), int):
        return f"{data['total']} found"
    if isinstance(data.get("nodes"), list):
        return f"{len(data['nodes'])} connected records"
    if data.get("found") is False:
        return "not found"
    if data.get("found") is True:
        return "1 record"
    return ""


class _ThinkFilter:
    """Drops a <think>…</think> block from text that arrives a few characters at a time, for models that
    narrate their reasoning in the answer instead of in a separate field. A tag split across two pieces
    is held back until it can be told apart."""

    def __init__(self):
        self.inside = False
        self.pending = ""

    def feed(self, piece: str) -> str:
        text, out = self.pending + piece, []
        self.pending = ""
        while text:
            tag = "</think>" if self.inside else "<think>"
            at = text.lower().find(tag)
            if at >= 0:
                if not self.inside:
                    out.append(text[:at])
                text, self.inside = text[at + len(tag):], not self.inside
                continue
            keep = next((k for k in range(min(len(tag) - 1, len(text)), 0, -1)
                         if tag.startswith(text[-k:].lower())), 0)
            if not self.inside:
                out.append(text[:len(text) - keep])
            self.pending = text[len(text) - keep:] if keep else ""
            break
        return "".join(out)


def ask_events(db: Session, workspace_id: str, endpoint: Endpoint, question: str,
               history: Optional[list] = None, stream: bool = True, proposer=None,
               context: Optional[str] = None):
    """The answer to a question, as it is worked out: what the model is doing, each lookup as it starts
    and what it found, the answer as it is written, and last the whole of it ("done").

    Events: {"type": "thinking", "text"}, {"type": "text", "text"}, {"type": "text_reset"} (what was
    written turned out to precede lookups, not to be the answer), {"type": "step_start", "index", "tool",
    "arguments"}, {"type": "step", "index", "tool", "arguments", "result", "error", "seconds",
    "summary"}, {"type": "proposal", "action"}, {"type": "done", "answer", "steps", "stopped", "seconds", "error"}.

    With a `proposer` (services/ask_actions.py) the model may also propose changes, which it keeps for the
    person to apply; `context` says what became of the ones proposed earlier in the conversation.
    """
    from app.services import ask_actions
    system = SYSTEM + (ask_actions.SYSTEM if proposer else "")
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}, *_history(history),
                                      *([{"role": "system", "content": context}] if context else []),
                                      {"role": "user", "content": question}]
    tools = _tool_specs() + (ask_actions.tool_specs() if proposer else [])
    steps: list[dict] = []
    started = time.monotonic()

    def turn(with_tools: bool):
        """One model turn; yields events, and returns the assistant message."""
        if not stream:
            message = converse(endpoint, messages, tools=tools if with_tools else None)
            return message
        think = _ThinkFilter()
        message: dict = {}
        wrote = False
        for kind, value in converse_stream(endpoint, messages, tools=tools if with_tools else None):
            if kind == "reasoning":
                yield {"type": "thinking", "text": value}
            elif kind == "content":
                visible = think.feed(str(value))
                if visible:
                    wrote = True
                    yield {"type": "text", "text": visible}
            elif kind == "message":
                message = value  # type: ignore[assignment]
        if wrote and message.get("tool_calls"):
            yield {"type": "text_reset"}
        return message

    def done(answer: str, stopped: str, error: Optional[str] = None) -> dict:
        return {"type": "done", "answer": answer, "steps": steps, "stopped": stopped, "error": error,
                "seconds": round(time.monotonic() - started, 1)}

    for _round in range(MAX_ROUNDS):
        message = yield from turn(True)
        calls = message.get("tool_calls") or []
        if not calls:
            yield done(_answer_of(message), "answered")
            return

        # The assistant's own message has to go back verbatim, tool calls
        # and all, or the results that follow refer to nothing.
        messages.append({
            "role": "assistant",
            "content": message.get("content") or "",
            "tool_calls": calls,
        })

        for call in calls:
            name = (call.get("function") or {}).get("name") or ""
            arguments = _arguments_of(call)
            index = len(steps)
            yield {"type": "step_start", "index": index, "tool": name, "arguments": arguments}
            at = time.monotonic()
            proposal = None
            if proposer is not None and name in ask_actions.TOOL_NAMES:
                try:
                    out = proposer(name, arguments)
                    proposal = out.pop("_action")
                    text, error = json.dumps(out, ensure_ascii=False), None
                except ask_actions.Refused as e:
                    text = error = f"Not proposed: {e}"
            else:
                text, error = _run_tool(db, workspace_id, name, arguments)
            step = {"tool": name, "arguments": arguments, "result": text, "error": error,
                    "seconds": round(time.monotonic() - at, 1)}
            steps.append(step)
            yield {"type": "step", "index": index, **step,
                   "summary": f"proposed A{proposal['number']}" if proposal else _summary(name, text, error)}
            if proposal:
                yield {"type": "proposal", "action": proposal}
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id") or name,
                "content": text,
            })

    # Out of rounds. Ask for the answer it has rather than returning
    # nothing, but say plainly that it was cut short.
    messages.append({
        "role": "user",
        "content": "Stop looking things up and answer with what you have found so far.",
    })
    try:
        final = yield from turn(False)
    except LLMError as e:
        yield done("", "exhausted", str(e))
        return
    yield done(_answer_of(final), "exhausted")


def ask(db: Session, workspace_id: str, endpoint: Endpoint, question: str,
        history: Optional[list] = None) -> dict:
    """A question, the answer, and every record the answer was built from — all at once."""
    result: dict = {}
    for event in ask_events(db, workspace_id, endpoint, question, history=history, stream=False):
        if event["type"] == "done":
            result = event
    out = {k: v for k, v in result.items() if k != "type"}
    if not out.get("error"):
        out.pop("error", None)
    return out
