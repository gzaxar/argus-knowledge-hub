"""Talking to an OpenAI-compatible endpoint.

Deliberately generic: INFN runs several AI gateways and a workspace points
at whichever one it is entitled to use, so nothing here knows about a
particular provider. The endpoint is whatever answers `/v1/models` and
`/v1/chat/completions`.

Checking one is not the same as pinging it. Three separate things fail in
practice — the host is unreachable, the key is rejected, or the model name
is not one this endpoint serves — and the third passes a naive health
check and then fails on first use, so it is checked explicitly.
"""
import json
import logging
import time
from dataclasses import dataclass
from typing import Iterator, Optional

import requests

TIMEOUT_SECONDS = 30
# Long enough for a real classification over a page of text.
COMPLETION_TIMEOUT_SECONDS = 120

log = logging.getLogger(__name__)


class ModelSettings:
    """How one model is called (AI settings › per-model settings). `temperature` None: ARGUS's default for the
    call (0 to classify and chat; the model's own for a structured answer, since a reasoning model's thinking
    runs on at 0)."""

    def __init__(self, temperature: Optional[float] = None, no_thinking: bool = True, json_mode: bool = True,
                 time_limit_s: Optional[int] = None):
        self.temperature, self.no_thinking, self.json_mode = temperature, no_thinking, json_mode
        self.time_limit_s = time_limit_s

    @classmethod
    def of(cls, raw: Optional[dict]) -> "ModelSettings":
        raw = raw or {}
        t = raw.get("temperature")
        limit = raw.get("time_limit_s")
        return cls(temperature=float(t) if isinstance(t, (int, float)) and not isinstance(t, bool) else None,
                   no_thinking=raw.get("no_thinking") is not False, json_mode=raw.get("json_mode") is not False,
                   time_limit_s=int(limit) if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0 else None)


@dataclass
class Endpoint:
    base_url: str
    model: str
    embedding_model: Optional[str] = None
    vision_model: Optional[str] = None
    asr_model: Optional[str] = None
    tts_model: Optional[str] = None
    rerank_model: Optional[str] = None
    api_key: Optional[str] = None
    # The workspace's cap on a reply's length (AI settings); None: no limit, and no max_tokens is sent.
    max_output_tokens: Optional[int] = None
    # The model for answers that are data (AI settings); None: `model`.
    structured_model: Optional[str] = None
    # How each model is called, by name (AI settings › per-model settings).
    model_settings: Optional[dict] = None

    def settings(self, model: Optional[str] = None) -> ModelSettings:
        """How `model` (by default the chat model) is called."""
        return ModelSettings.of((self.model_settings or {}).get(model or self.model))

    def temperature(self, model: Optional[str], default: Optional[float]) -> dict:
        """The temperature to send: the model's setting, or `default` (None: none sent, the model's own)."""
        t = self.settings(model).temperature
        t = default if t is None else t
        return {} if t is None else {"temperature": t}

    @property
    def root(self) -> str:
        return self.base_url.rstrip("/")

    def budget(self) -> dict:
        """The request's length limit: one the workspace set, or none. Not one per call: a budget sized
        for the answer is what a reasoning model spends thinking, and then there is no answer."""
        return {"max_tokens": self.max_output_tokens} if self.max_output_tokens else {}

    def headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


class LLMError(RuntimeError):
    """Something the caller should show a person, not a stack trace."""


def _post(purpose: str, model: Optional[str], url: str, **kwargs) -> requests.Response:
    """requests.post, counted for the usage statistics: the call, how long it took and the tokens the provider
    reports (estimated from the text when it reports none; services/usage.py)."""
    from app.services import usage
    started = time.monotonic()
    try:
        resp = requests.post(url, **kwargs)
    except requests.RequestException:
        usage.note_llm(model, purpose, seconds=time.monotonic() - started, failed=True, prompt_tokens=0,
                       completion_tokens=0)
        raise
    if kwargs.get("stream"):
        return resp                                     # converse_stream counts it as it ends
    reported, text = None, ""
    if resp.status_code < 400:
        try:
            body = resp.json()
            reported = body.get("usage") if isinstance(body, dict) else None
            if not reported and isinstance(body, dict):
                text = str(((body.get("choices") or [{}])[0].get("message") or {}).get("content") or body.get("text")
                           or "")
        except (ValueError, AttributeError, IndexError):
            pass
    sent = kwargs.get("json") or kwargs.get("data") or {}
    usage.note_llm(model, purpose, seconds=time.monotonic() - started, failed=resp.status_code >= 400,
                   prompt_tokens=(reported or {}).get("prompt_tokens") if reported else None,
                   completion_tokens=(reported or {}).get("completion_tokens", 0) if reported else None,
                   prompt_text="" if reported else json.dumps(sent.get("messages") or sent.get("input")
                                                              or sent.get("documents") or "", ensure_ascii=False),
                   completion_text=text)
    return resp


def list_models(endpoint: Endpoint) -> list[str]:
    try:
        resp = requests.get(
            f"{endpoint.root}/models", headers=endpoint.headers(), timeout=TIMEOUT_SECONDS
        )
    except requests.RequestException as e:
        raise LLMError(f"Could not reach {endpoint.root}: {e}") from e

    if resp.status_code in (401, 403):
        raise LLMError("The endpoint rejected the API key.")
    if resp.status_code >= 400:
        raise LLMError(f"The endpoint answered {resp.status_code} listing its models.")
    try:
        return [m.get("id") for m in resp.json().get("data", []) if m.get("id")]
    except ValueError as e:
        raise LLMError("The endpoint's model list was not JSON — is this an OpenAI-compatible API?") from e


def check(endpoint: Endpoint) -> tuple[bool, Optional[str], list[str]]:
    """Whether this endpoint can actually serve what it was configured with.

    Returns (ok, error, models). The model names are checked against what
    the endpoint lists, because a wrong one passes every other test and
    then fails on the first real request.
    """
    try:
        models = list_models(endpoint)
    except LLMError as e:
        return False, str(e), []

    if endpoint.model not in models:
        available = ", ".join(models[:8]) or "none"
        return (
            False,
            f"This endpoint does not serve “{endpoint.model}”. It offers: {available}.",
            models,
        )
    if endpoint.embedding_model and endpoint.embedding_model not in models:
        return (
            False,
            f"This endpoint does not serve the embedding model “{endpoint.embedding_model}”.",
            models,
        )
    if endpoint.vision_model and endpoint.vision_model not in models:
        return (
            False,
            f"This endpoint does not serve the vision model “{endpoint.vision_model}”.",
            models,
        )
    # Speech is checked here for the same reason as the rest: a wrong name
    # would otherwise surface at a microphone, mid-shift, in a control room.
    if endpoint.asr_model and endpoint.asr_model not in models:
        return (
            False,
            f"This endpoint does not serve the speech-to-text model “{endpoint.asr_model}”.",
            models,
        )
    if endpoint.rerank_model:
        try:
            order = rerank(endpoint, "accelerator vacuum", ["ion pump pressure", "a recipe for bread"])
        except LLMError as e:
            return False, f"The re-ranker model “{endpoint.rerank_model}” did not answer: {e}", models
        if not order:
            return False, f"The re-ranker model “{endpoint.rerank_model}” returned no ranking.", models
    if endpoint.tts_model and endpoint.tts_model not in models:
        return (
            False,
            f"This endpoint does not serve the text-to-speech model “{endpoint.tts_model}”.",
            models,
        )

    # Listing models often needs no key even where using one does, so the
    # key is only really tested by asking for something.
    try:
        resp = requests.post(
            f"{endpoint.root}/chat/completions",
            headers=endpoint.headers(),
            json={
                "model": endpoint.model,
                "messages": [{"role": "user", "content": "Reply with: ok"}],
                "max_tokens": 5,
            },
            timeout=COMPLETION_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        return False, f"Could not reach {endpoint.root}: {e}", models

    if resp.status_code in (401, 403):
        return False, "The endpoint rejected the API key.", models
    if resp.status_code >= 400:
        detail = (resp.text or "")[:200]
        return False, f"The endpoint answered {resp.status_code}: {detail}", models
    return True, None, models


def complete(endpoint: Endpoint, system: str, user: str,
             extra: Optional[dict] = None) -> str:
    """`extra` goes into the request as it is, for a provider-specific switch
    such as vLLM's chat_template_kwargs; a provider that rejects it answers 400."""
    try:
        resp = _post("complete", endpoint.model, 
            f"{endpoint.root}/chat/completions",
            headers=endpoint.headers(),
            json={
                "model": endpoint.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                **endpoint.budget(),
                # Classification should not wander between runs (unless the model's settings say otherwise).
                **endpoint.temperature(endpoint.model, 0),
                **(extra or {}),
            },
            timeout=COMPLETION_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        raise LLMError(f"Could not reach {endpoint.root}: {e}") from e
    if resp.status_code >= 400:
        raise LLMError(f"The endpoint answered {resp.status_code}: {(resp.text or '')[:200]}")
    try:
        return resp.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError) as e:
        raise LLMError("The endpoint's reply was not in the expected shape.") from e


# vLLM's switch for a reasoning model (Qwen, DeepSeek…) to answer without thinking first.
NO_THINKING = {"chat_template_kwargs": {"enable_thinking": False}}


# How long a structured answer may take, reasoning included: under the INFN gateway's own 300 s, so ARGUS says
# what happened instead of the gateway cutting the connection.
STRUCTURED_DEADLINE_SECONDS = 280


class LLMOvertime(LLMError):
    """A model that kept reasoning past the deadline without answering (a reasoning model that cannot be told
    not to think, such as the INFN gateway's minimax)."""

    def __init__(self, message: str, model: Optional[str] = None, reasoning_chars: int = 0,
                 limit_s: int = STRUCTURED_DEADLINE_SECONDS):
        super().__init__(message)
        self.model, self.reasoning_chars, self.limit_s = model, reasoning_chars, limit_s


class LLMRepeating(LLMError):
    """A model caught writing the same words over and over: it would go on until someone stopped it."""


class _RepeatWatch:
    """Notices a stream going round in circles: its end is the same block several times over, word for word.
    A long table is not that (its rows differ). A loop longer than the window is left to the time limit."""

    WINDOW, NEEDLE, COPIES, AT_LEAST, EVERY = 8000, 120, 4, 800, 200

    def __init__(self) -> None:
        self.tail, self.unread = "", 0

    def feed(self, text: str) -> bool:
        self.tail = (self.tail + text)[-self.WINDOW:]
        self.unread += len(text)
        if self.unread < self.EVERY or len(self.tail) < self.AT_LEAST:
            return False
        self.unread = 0
        at = self.tail.rfind(self.tail[-self.NEEDLE:], 0, len(self.tail) - 1)
        if at < 0:
            return False
        period = len(self.tail) - self.NEEDLE - at
        copies = max(self.COPIES, -(-self.AT_LEAST // period))
        return period * copies <= len(self.tail) and self.tail[-period * copies:] == self.tail[-period:] * copies


def _collect(endpoint: Endpoint, resp, started: float, model: str,
             limit: int) -> tuple[str, Optional[str], Optional[str], Optional[dict], int]:
    """(content, finish reason, model that answered, usage, characters of reasoning) of a streamed answer — or of
    a whole one, from a provider that does not stream. Reasoning is read as it comes and left aside."""
    if (resp.headers.get("content-type") or "").startswith("application/json"):
        try:
            body = resp.json()
            choice = body["choices"][0]
            msg = choice["message"]
        except (ValueError, KeyError, IndexError, AttributeError, TypeError) as e:
            raise LLMError("The endpoint's reply was not in the expected shape.") from e
        thought = msg.get("reasoning_content") or msg.get("reasoning") or ""
        return msg.get("content") or "", choice.get("finish_reason"), body.get("model"), body.get("usage"), len(thought)
    content: list[str] = []
    finish = served = None
    reported: Optional[dict] = None
    thought = 0
    deadline = started + limit
    for line in resp.iter_lines(decode_unicode=True):
        if time.monotonic() > deadline:
            raise LLMOvertime(f"{served or model} was still reasoning after {limit} s ({thought} characters of it) "
                              "and had not begun its answer"
                              if not content else
                              f"{served or model} had not finished its answer after {limit} s", served or model, thought,
                              limit)
        if not line or not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except ValueError:
            continue
        served = chunk.get("model") or served
        if chunk.get("usage"):
            reported = chunk["usage"]
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            thinking = delta.get("reasoning") or delta.get("reasoning_content")
            if thinking:
                thought += len(thinking)
            if delta.get("content"):
                content.append(delta["content"])
            if choice.get("finish_reason"):
                finish = choice["finish_reason"]
    return "".join(content), finish, served, reported, thought


def complete_structured(endpoint: Endpoint, system: str, user: str) -> str:
    """`complete` for an answer that is data (a JSON object), not prose.

    Streamed, so the answer is read as the model writes it: a reasoning model that cannot be told not to think
    (the INFN gateway's minimax, measured 2026-11-03) reasons first, and a request that waits for the whole
    reply in silence is cut by the gateway at 300 s. Its reasoning is read and left aside; past its time limit
    ARGUS stops and says so. The model is the AI settings' model for structured work (else the chat model),
    called as its per-model settings say: by default at its own temperature (at 0 a reasoning model's thinking
    runs on and on), in JSON mode, told not to think, within STRUCTURED_DEADLINE_SECONDS. Each switch is dropped
    in turn when the provider refuses it (400/422), streaming last. A request left with no answer at all is sent once more. A reply
    cut off before any answer is an error that says so, not an empty answer."""
    from app.services import usage
    model = endpoint.structured_model or endpoint.model
    settings = endpoint.settings(model)
    deadline = settings.time_limit_s or STRUCTURED_DEADLINE_SECONDS
    base = {"model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            **endpoint.budget(), **endpoint.temperature(model, None), "stream": True}
    # The switches this model is asked for, the most first; each dropped in turn when the provider refuses it.
    thinking = NO_THINKING if settings.no_thinking else {}
    tries = ([{"response_format": {"type": "json_object"}, **thinking}] if settings.json_mode else []) + [thinking]
    if tries[-1]:
        tries.append({})
    tries.append({"stream": False})                    # a provider that does not stream: the whole reply
    for extra in tries:
        refused = False
        for attempt in (1, 2):
            started = time.monotonic()
            try:
                resp = _post("structured", model, f"{endpoint.root}/chat/completions",
                             headers=endpoint.headers(), json={**base, **extra}, stream=True,
                             timeout=COMPLETION_TIMEOUT_SECONDS)
            except requests.Timeout as e:
                if attempt == 2:
                    raise LLMError(f"Could not reach {endpoint.root} (no answer, twice): {e}") from e
                log.warning("structured request to %s left without an answer; sending it again", endpoint.root)
                continue
            except requests.RequestException as e:
                raise LLMError(f"Could not reach {endpoint.root}: {e}") from e
            if resp.status_code in (400, 422):
                resp.close()
                refused = True
                break
            if resp.status_code >= 400:
                detail = (resp.text or "")[:200]
                resp.close()
                raise LLMError(f"The endpoint answered {resp.status_code}: {detail}")
            content, finish, served, reported, thought = "", None, None, None, 0
            try:
                content, finish, served, reported, thought = _collect(endpoint, resp, started, model, deadline)
            except requests.RequestException as e:
                # Silent for the whole read timeout, or the connection dropped: once more.
                if attempt == 2:
                    raise LLMError(f"Could not reach {endpoint.root} (no answer, twice): {e}") from requests.Timeout(str(e))
                log.warning("structured answer from %s stopped arriving; sending the request again", endpoint.root)
                continue
            finally:
                resp.close()
                usage.note_llm(model, "structured", seconds=time.monotonic() - started,
                               prompt_tokens=(reported or {}).get("prompt_tokens") if reported else None,
                               completion_tokens=(reported or {}).get("completion_tokens") if reported else None,
                               prompt_text="" if reported else system + user,
                               completion_text="" if reported else content)
            if not content.strip() and finish == "length":
                raise LLMError(f"{served or model} used all {endpoint.max_output_tokens} tokens before "
                               "answering (a reasoning model that kept thinking): nothing to read. Raise or clear "
                               "the output-token limit in the AI settings.")
            return Reply(content, cut_off=finish == "length", model=served or model)
        if not refused:
            break
    raise LLMError(f"{endpoint.root} refused every form of the request for {model} (400/422): check the model's "
                   "name and its settings in the AI settings")


class Reply(str):
    """A model's answer that also says whether it was cut off at the output-token limit (`cut_off`): a JSON
    answer cut short does not parse, and the reason is then that, not a model that ignored the format — and
    which model answered (`model`: the one a gateway's "auto" chose), for the error that names it."""

    def __new__(cls, text: str, cut_off: bool = False, model: Optional[str] = None):
        out = super().__new__(cls, text)
        out.cut_off = cut_off
        out.model = model
        return out


def rerank(endpoint: Endpoint, query: str, documents: list[str]) -> list[tuple[int, float]]:
    """(index, score) of the documents, most relevant first, from the endpoint's re-ranker: the /rerank API
    that vLLM, Infinity, Jina and Cohere-style gateways serve ({model, query, documents} → results[index,
    relevance_score])."""
    if not endpoint.rerank_model or not documents:
        return [(i, 0.0) for i in range(len(documents))]
    body = {"model": endpoint.rerank_model, "query": query, "documents": documents, "top_n": len(documents)}
    last = None
    # Gateways expose it at /rerank or, beside the OpenAI routes, at /v1/rerank.
    roots = [endpoint.root] + ([endpoint.root + "/v1"] if not endpoint.root.endswith("/v1") else [])
    for root in roots:
        try:
            resp = _post("rerank", endpoint.rerank_model, f"{root}/rerank", headers=endpoint.headers(), json=body, timeout=TIMEOUT_SECONDS * 6)
        except requests.RequestException as e:
            raise LLMError(f"Could not reach {endpoint.root}: {e}") from e
        if resp.status_code == 404:
            last = resp
            continue
        if resp.status_code >= 400:
            raise LLMError(f"The re-ranker answered {resp.status_code}: {(resp.text or '')[:200]}")
        try:
            results = resp.json().get("results") or resp.json().get("data") or []
            ranked = [(int(r["index"]), float(r.get("relevance_score", r.get("score", 0.0)))) for r in results]
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            raise LLMError("The re-ranker's reply was not in the expected shape.") from e
        return sorted(ranked, key=lambda x: -x[1])
    raise LLMError(f"This endpoint serves no /rerank route (answered {last.status_code if last else '?'})")


def converse(endpoint: Endpoint, messages: list[dict], tools: Optional[list[dict]] = None) -> dict:
    """One turn of a tool-calling conversation; returns the assistant message.

    Unlike `complete`, the caller owns the message list, because a tool
    call and its result have to be appended in the exact shape the model
    sent them or the next turn is rejected.
    """
    payload: dict = {
        "model": endpoint.model,
        "messages": messages,
        **endpoint.budget(),
        **endpoint.temperature(endpoint.model, 0),
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    try:
        resp = _post("chat", endpoint.model, 
            f"{endpoint.root}/chat/completions",
            headers=endpoint.headers(),
            json=payload,
            timeout=COMPLETION_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        raise LLMError(f"Could not reach {endpoint.root}: {e}") from e
    if resp.status_code >= 400:
        detail = (resp.text or "")[:300]
        # Worth naming: a model that does not do tool calling fails here,
        # and "400 Bad Request" alone sends somebody looking at the network.
        if "tool" in detail.lower():
            raise LLMError(
                f"The endpoint refused a tool-calling request — “{endpoint.model}” may not "
                f"support tools. It answered {resp.status_code}: {detail}"
            )
        raise LLMError(f"The endpoint answered {resp.status_code}: {detail}")
    try:
        return resp.json()["choices"][0]["message"]
    except (ValueError, KeyError, IndexError) as e:
        raise LLMError("The endpoint's reply was not in the expected shape.") from e


def converse_stream(endpoint: Endpoint, messages: list[dict], tools: Optional[list[dict]] = None,
                    fresh: bool = False) -> Iterator[tuple[str, object]]:
    """One turn of a tool-calling conversation, as it is written.

    Yields ("reasoning", text) while a reasoning model thinks, ("content", text) as the answer is
    written, and last ("message", message): the assistant message assembled from the pieces, in the shape
    `converse` returns, tool calls included. A tool call arrives in fragments (its name, then its
    arguments a few characters at a time) keyed by index, and is only usable once the stream ends.

    Raises LLMRepeating when the model goes round in circles and LLMOvertime past the model's time limit, so
    neither runs until someone presses Stop. `fresh`: the second try after a loop, at the model's own temperature
    (a reasoning model's thinking runs on at 0) and told not to think, as its settings allow.
    """
    from app.services import usage
    # The tokens used come in a last chunk when asked for (OpenAI, vLLM); a provider that does not know the
    # option refuses it, and is asked again without.
    payload: dict = {"model": endpoint.model, "messages": messages, **endpoint.budget(),
                     **endpoint.temperature(endpoint.model, None if fresh else 0), "stream": True,
                     "stream_options": {"include_usage": True}}
    if fresh and endpoint.settings().no_thinking:
        payload.update(NO_THINKING)
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    started = time.monotonic()
    limit = endpoint.settings().time_limit_s or STRUCTURED_DEADLINE_SECONDS
    try:
        for _ in range(3):                             # each option the provider refuses is dropped in turn
            resp = _post("chat", endpoint.model, f"{endpoint.root}/chat/completions", headers=endpoint.headers(),
                         json=payload, stream=True, timeout=COMPLETION_TIMEOUT_SECONDS)
            if resp.status_code not in (400, 422):
                break
            if "stream_options" in payload and "stream_options" in (resp.text or ""):
                payload.pop("stream_options")
            elif "chat_template_kwargs" in payload:
                payload.pop("chat_template_kwargs")
            else:
                break
    except requests.RequestException as e:
        raise LLMError(f"Could not reach {endpoint.root}: {e}") from e
    if resp.status_code >= 400:
        detail = (resp.text or "")[:300]
        usage.note_llm(endpoint.model, "chat", seconds=time.monotonic() - started, failed=True, prompt_tokens=0,
                       completion_tokens=0)
        raise LLMError(f"The endpoint answered {resp.status_code}: {detail}")
    content: list[str] = []
    thought: list[str] = []
    calls: dict[int, dict] = {}
    reported: Optional[dict] = None
    thought_watch, content_watch = _RepeatWatch(), _RepeatWatch()
    try:
        for line in resp.iter_lines(decode_unicode=True):
            if time.monotonic() - started > limit:
                raise LLMOvertime(f"{endpoint.model} had not finished after {limit} s and was stopped",
                                  endpoint.model, sum(map(len, thought)), limit)
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except ValueError:
                continue
            if chunk.get("usage"):
                reported = chunk["usage"]
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            thinking = delta.get("reasoning") or delta.get("reasoning_content")
            if thinking:
                thought.append(thinking)
                yield "reasoning", thinking
                if thought_watch.feed(thinking):
                    raise LLMRepeating(f"{endpoint.model} kept repeating the same reasoning and was stopped")
            if delta.get("content"):
                content.append(delta["content"])
                yield "content", delta["content"]
                if content_watch.feed(delta["content"]):
                    raise LLMRepeating(f"{endpoint.model} kept repeating the same text and was stopped")
            for piece in delta.get("tool_calls") or []:
                call = calls.setdefault(piece.get("index", 0),
                                        {"id": None, "type": "function", "function": {"name": "", "arguments": ""}})
                if piece.get("id"):
                    call["id"] = piece["id"]
                fn = piece.get("function") or {}
                if fn.get("name"):
                    call["function"]["name"] += fn["name"]
                if fn.get("arguments"):
                    call["function"]["arguments"] += fn["arguments"]
    except requests.RequestException as e:
        raise LLMError(f"The connection to {endpoint.root} dropped: {e}") from e
    finally:
        resp.close()
        usage.note_llm(endpoint.model, "chat", seconds=time.monotonic() - started,
                       prompt_tokens=(reported or {}).get("prompt_tokens") if reported else None,
                       completion_tokens=(reported or {}).get("completion_tokens", 0) if reported else None,
                       prompt_text="" if reported else json.dumps(messages, ensure_ascii=False, default=str),
                       completion_text="".join(thought) + "".join(content)
                       + json.dumps(list(calls.values()), ensure_ascii=False))
    message: dict = {"role": "assistant", "content": "".join(content)}
    if calls:
        message["tool_calls"] = [calls[i] for i in sorted(calls)]
    yield "message", message


def embed(endpoint: Endpoint, texts: list[str]) -> list[list[float]]:
    """Vectors for a batch of texts, in the order given."""
    if not endpoint.embedding_model:
        raise LLMError("No embedding model is configured for this endpoint.")
    if not texts:
        return []
    try:
        resp = _post("embed", endpoint.embedding_model, 
            f"{endpoint.root}/embeddings",
            headers=endpoint.headers(),
            json={"model": endpoint.embedding_model, "input": texts},
            timeout=COMPLETION_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        raise LLMError(f"Could not reach {endpoint.root}: {e}") from e
    if resp.status_code >= 400:
        raise LLMError(f"The endpoint answered {resp.status_code}: {(resp.text or '')[:200]}")
    try:
        data = sorted(resp.json()["data"], key=lambda row: row.get("index", 0))
        return [row["embedding"] for row in data]
    except (ValueError, KeyError) as e:
        raise LLMError("The endpoint's embeddings reply was not in the expected shape.") from e


def transcribe(endpoint: Endpoint, audio: bytes, filename: str, mime_type: str,
               language: Optional[str] = None) -> str:
    """What was said in a recording, as text: the endpoint's speech-to-text model (a Whisper), through the
    OpenAI-compatible /audio/transcriptions."""
    if not endpoint.asr_model:
        raise LLMError("No speech-to-text model is configured for this endpoint.")
    headers = {k: v for k, v in endpoint.headers().items() if k != "Content-Type"}  # multipart sets its own
    data = {"model": endpoint.asr_model, "response_format": "json"}
    if language:
        data["language"] = language
    try:
        resp = _post("transcribe", endpoint.asr_model, f"{endpoint.root}/audio/transcriptions", headers=headers, data=data,
                             files={"file": (filename, audio, mime_type)}, timeout=COMPLETION_TIMEOUT_SECONDS * 3)
    except requests.RequestException as e:
        raise LLMError(f"Could not reach {endpoint.root}: {e}") from e
    if resp.status_code >= 400:
        raise LLMError(f"The endpoint answered {resp.status_code}: {(resp.text or '')[:200]}")
    try:
        return (resp.json().get("text") or "").strip()
    except ValueError:
        return (resp.text or "").strip()


def look(endpoint: Endpoint, image: bytes, mime_type: str, system: str, user: str) -> str:
    """Ask the vision model about a picture.

    A separate model from `complete`'s, because they usually are: the chat
    model a workspace picks for text answers "not a multimodal model" when
    shown an image, and finding that out at the point of use rather than at
    configuration time is exactly what the check exists to prevent.
    """
    if not endpoint.vision_model:
        raise LLMError("No vision model is configured for this endpoint.")
    import base64

    encoded = base64.b64encode(image).decode("ascii")
    try:
        resp = _post("vision", endpoint.vision_model, 
            f"{endpoint.root}/chat/completions",
            headers=endpoint.headers(),
            json={
                "model": endpoint.vision_model,
                "messages": [
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                            },
                        ],
                    },
                ],
                **endpoint.budget(),
                **endpoint.temperature(endpoint.vision_model, 0),
            },
            timeout=COMPLETION_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        raise LLMError(f"Could not reach {endpoint.root}: {e}") from e
    if resp.status_code >= 400:
        raise LLMError(f"The endpoint answered {resp.status_code}: {(resp.text or '')[:200]}")
    try:
        return resp.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError) as e:
        raise LLMError("The endpoint's reply was not in the expected shape.") from e
