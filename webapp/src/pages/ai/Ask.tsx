import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { aiApi, ApiError, streamChat } from "../../api/client";
import type { AskAction, AskMessage, AskStep, ChatEvent } from "../../api/types";
import { MarkdownView } from "../../components/MarkdownView";
import { useCurrentWorkspaceId } from "../../api/useCurrentWorkspaceId";

/** Ask ARGUS, as a conversation.
 *
 * Answers come only from this workspace's records, and the lookups they rest on are shown as they run:
 * an answer with no lookups behind it is the model talking about some other laboratory, and it should be
 * obvious at a glance. The answer is written as it arrives, a follow-up continues the conversation with
 * the earlier turns as context, and every key an answer cites links to its record. */

const STARTERS = [
  "How many objects, tickets and documents are in this workspace?",
  "Can you list the magnets?",
  "Which procedures cover the vacuum system?",
  "What has gone wrong with the BTF line before?",
];

/** What each lookup is, in words. */
const TOOL_WORDS: Record<string, string> = {
  search_objects: "Searching equipment",
  list_types: "Looking up the types",
  get_object: "Opening a record",
  search_tickets: "Searching tickets",
  get_ticket: "Opening a ticket",
  search_documents: "Searching documentation",
  search_knowledge: "Reading what is written",
  get_document: "Opening a document",
  graph_neighbours: "Following connections",
  impact_analysis: "Working out what depends on it",
  root_cause_analysis: "Looking for root causes",
  root_cause_from_alarms: "Looking for the cause of the alarms",
  single_points_of_failure: "Looking for single points of failure",
  knowledge_summary: "Counting what this workspace holds",
  search_help: "Reading the user guide",
  read_help: "Opening a guide topic",
  propose_create_record: "Proposing a new record",
  propose_update_record: "Proposing a change",
  propose_relation: "Proposing a relation",
};

interface Turn {
  id: string;
  role: "user" | "assistant";
  content: string;
  steps: (AskStep & { running?: boolean; summary?: string })[];
  thinking: string;
  stopped: string | null;
  error: string | null;
  seconds: number | null;
  live?: boolean;
  /** The message's place in the conversation (a saved turn); its proposals carry the question's seq. */
  seq?: number;
  /** Proposals made while this turn streamed. */
  actions?: AskAction[];
}

function fromMessage(m: AskMessage): Turn {
  return {
    id: m.id, role: m.role, content: m.content, steps: m.steps ?? [], thinking: "",
    stopped: m.stopped, error: m.error, seconds: m.seconds, seq: m.seq,
  };
}

function argsText(args: Record<string, unknown>): string {
  return Object.entries(args)
    .filter(([k, v]) => v !== null && v !== undefined && v !== "" && k !== "limit")
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : typeof v === "string" ? v : JSON.stringify(v)}`)
    .join(" · ");
}

function summaryOf(step: AskStep & { summary?: string }): string {
  if (step.summary !== undefined) return step.summary;
  if (step.error) return step.error;
  try {
    const data = JSON.parse(step.result) as Record<string, unknown>;
    if (data.available === false) return "not available here";
    if (Array.isArray(data.results)) return `${data.results.length} passages`;
    if (typeof data.total === "number") return `${data.total} found`;
    if (Array.isArray(data.nodes)) return `${data.nodes.length} connected records`;
    if (data.found === false) return "not found";
    if (data.found === true) return "1 record";
  } catch {
    /* not JSON: nothing to summarise */
  }
  return "";
}

/** Every record the lookups returned, by the key or code an answer cites it with, to its page. */
function recordLinks(steps: AskStep[]): Map<string, string> {
  const links = new Map<string, string>();
  const walk = (v: unknown) => {
    if (Array.isArray(v)) return v.forEach(walk);
    if (!v || typeof v !== "object") return;
    const o = v as Record<string, unknown>;
    if (typeof o.uid === "string") {
      if (typeof o.key === "string") links.set(o.key, `/assets/${encodeURIComponent(o.uid)}`);
      if (typeof o.code === "string") links.set(o.code, `/documents/${encodeURIComponent(o.uid)}`);
      if (typeof o.source_key === "string") links.set(o.source_key, `/tickets/${encodeURIComponent(o.uid)}`);
    }
    Object.values(o).forEach(walk);
  };
  for (const s of steps) {
    try {
      walk(JSON.parse(s.result));
    } catch {
      /* a truncated result is not JSON; its records just are not linked */
    }
  }
  return links;
}

const escapeRegExp = (t: string) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** The answer with every record code it names as plain text made a link too.
 * Codes in backticks are linked by MarkdownView already; a model does not
 * always write them that way. Code blocks, code spans and existing links are
 * left alone. */
function linkPlainCodes(markdown: string, links: Map<string, string>): string {
  const codes = [...links.keys()].filter((c) => c.length >= 3).sort((a, b) => b.length - a.length);
  if (codes.length === 0) return markdown;
  const pattern = new RegExp(`(?<![\\w:/.-])(${codes.map(escapeRegExp).join("|")})(?![\\w:/-])`, "g");
  return markdown
    .split(/(```[\s\S]*?```)/)
    .map((block, i) =>
      i % 2 === 1
        ? block
        : block
            .split(/(`[^`\n]*`|\[[^\]\n]*\]\([^)\n]*\))/)
            .map((part, j) => (j % 2 === 1 ? part : part.replace(pattern, (code) => `[${code}](${links.get(code)})`)))
            .join(""),
    )
    .join("");
}

function StepRow({ step }: { step: Turn["steps"][number] }) {
  const [open, setOpen] = useState(false);
  const summary = step.running ? "" : summaryOf(step);
  return (
    <li>
      <button
        type="button"
        onClick={() => !step.running && setOpen((v) => !v)}
        className="flex w-full items-baseline gap-2 rounded px-2 py-1 text-left text-xs hover:bg-slate-50"
      >
        <span className={`shrink-0 ${step.error ? "text-rose-500" : step.running ? "text-indigo-500" : "text-emerald-600"}`}>
          {step.running ? <Spinner /> : step.error ? "✕" : "✓"}
        </span>
        <span className="shrink-0 font-medium text-slate-700">{TOOL_WORDS[step.tool] ?? step.tool}</span>
        <span className="min-w-0 flex-1 truncate text-slate-500">{argsText(step.arguments)}</span>
        {summary && <span className={`shrink-0 ${step.error ? "text-rose-600" : "text-slate-500"}`}>{summary}</span>}
        {!step.running && <span className="shrink-0 text-slate-400">{open ? "▾" : "▸"}</span>}
      </button>
      {open && (
        <pre className="mx-2 mb-1 max-h-72 overflow-auto rounded bg-slate-50 px-2 py-1 text-[11px] leading-relaxed text-slate-700">
          {step.result}
        </pre>
      )}
    </li>
  );
}

function Spinner() {
  return <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-indigo-200 border-t-indigo-600 align-middle" />;
}

const STATUS: Record<AskAction["status"], { mark: string; tone: string; word: string }> = {
  proposed: { mark: "○", tone: "text-indigo-600", word: "waiting for you" },
  applied: { mark: "✓", tone: "text-emerald-600", word: "applied" },
  failed: { mark: "✕", tone: "text-rose-600", word: "failed" },
  discarded: { mark: "–", tone: "text-slate-400", word: "discarded" },
};

/** The changes a turn proposed. Nothing has changed until they are applied here, and then they go
 * through the same checks as the forms, with your permissions, in your name. */
function ProposedChanges({ actions, conversationId }: { actions: AskAction[]; conversationId: string | null }) {
  const queryClient = useQueryClient();
  const pending = actions.filter((a) => a.status === "proposed");
  const [chosen, setChosen] = useState<Set<string>>(() => new Set(pending.map((a) => a.id)));
  useEffect(() => {
    setChosen((was) => new Set([...was, ...pending.filter((a) => !was.has(a.id)).map((a) => a.id)]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending.length]);
  const decide = useMutation({
    mutationFn: ({ apply, ids }: { apply: boolean; ids: string[] }) =>
      apply ? aiApi.applyActions(conversationId!, ids) : aiApi.discardActions(conversationId!, ids),
    onSuccess: (all) => {
      queryClient.setQueryData(["ask-actions", conversationId], all);
      void queryClient.invalidateQueries({ queryKey: ["assets"] });
    },
  });
  const ids = pending.filter((a) => chosen.has(a.id)).map((a) => a.id);
  return (
    <div className="border-t border-slate-100 px-3 py-2">
      <p className="text-xs font-medium text-slate-700">
        Proposed changes{" "}
        <span className="font-normal text-slate-500">
          {pending.length ? "— nothing has been changed yet" : ""}
        </span>
      </p>
      <ul className="mt-1 space-y-0.5">
        {actions.map((a) => {
          const st = STATUS[a.status];
          return (
            <li key={a.id} className="flex items-start gap-2 text-xs">
              {a.status === "proposed" ? (
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={chosen.has(a.id)}
                  onChange={(e) =>
                    setChosen((was) => {
                      const next = new Set(was);
                      if (e.target.checked) next.add(a.id);
                      else next.delete(a.id);
                      return next;
                    })
                  }
                  aria-label={`Include A${a.number}`}
                />
              ) : (
                <span className={`w-3 shrink-0 text-center ${st.tone}`}>{st.mark}</span>
              )}
              <span className="shrink-0 font-mono text-slate-400">A{a.number}</span>
              <span className="min-w-0 flex-1">
                <span className="text-slate-800">{a.summary}</span>
                {a.reason && <span className="block text-slate-500">{a.reason}</span>}
                {a.status === "applied" && a.result?.uid && (
                  <Link className="ml-1 text-indigo-600 underline" to={`/assets/${encodeURIComponent(a.result.uid)}`}>
                    {a.result.key ?? "open"}
                  </Link>
                )}
                {a.status === "applied" && a.kind === "pull_request" && a.result?.url && (
                  <a className="ml-1 text-indigo-600 underline" href={a.result.url} target="_blank" rel="noreferrer">
                    {a.result.key ?? "pull request"}
                  </a>
                )}
                {a.status === "proposed" && a.kind === "pull_request" && (
                  <span className="block text-slate-500">
                    Applying opens a draft pull request that names you as the person who confirmed it; the
                    repository's reviewers decide, ARGUS does not merge it.
                  </span>
                )}
                {a.error && <span className="block text-rose-600">{a.error}</span>}
              </span>
              <span className={`shrink-0 ${st.tone}`}>{st.word}</span>
            </li>
          );
        })}
      </ul>
      {pending.length > 0 && (
        <div className="mt-2 flex items-center gap-2">
          <button
            type="button"
            disabled={!conversationId || !ids.length || decide.isPending}
            onClick={() => decide.mutate({ apply: true, ids })}
            className="rounded bg-slate-900 px-3 py-1 text-xs font-medium text-white disabled:bg-slate-300"
          >
            {decide.isPending ? "Applying…" : `Apply ${ids.length === pending.length ? "all" : ids.length}`}
          </button>
          <button
            type="button"
            disabled={!conversationId || !ids.length || decide.isPending}
            onClick={() => decide.mutate({ apply: false, ids })}
            className="rounded border border-slate-300 px-3 py-1 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Discard
          </button>
          {decide.isError && <span className="text-xs text-rose-600">{String((decide.error as Error).message)}</span>}
        </div>
      )}
    </div>
  );
}

function AssistantTurn({ turn, actions, conversationId }: {
  turn: Turn; actions: AskAction[]; conversationId: string | null;
}) {
  const [showThinking, setShowThinking] = useState(false);
  const links = useMemo(() => recordLinks(turn.steps), [turn.steps]);
  const working = turn.live && !turn.content;
  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      {turn.steps.length > 0 && (
        <ul className="border-b border-slate-100 px-1 py-1">
          {turn.steps.map((s, i) => <StepRow key={i} step={s} />)}
        </ul>
      )}
      {working && (
        <div className="px-4 py-2 text-xs text-slate-500">
          <Spinner />{" "}
          {turn.thinking ? "Thinking" : turn.steps.some((s) => s.running) ? "Looking it up" : "Starting"}…
          {turn.thinking && (
            <button type="button" onClick={() => setShowThinking((v) => !v)} className="ml-2 underline">
              {showThinking ? "hide reasoning" : "show reasoning"}
            </button>
          )}
          {showThinking && (
            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-2 text-[11px] text-slate-500">
              {turn.thinking.slice(-4000)}
            </pre>
          )}
        </div>
      )}
      {turn.content && (
        <div className="px-4 py-3">
          <MarkdownView markdown={linkPlainCodes(turn.content, links)} codeLink={(t) => links.get(t)} />
        </div>
      )}
      {actions.length > 0 && <ProposedChanges actions={actions} conversationId={conversationId} />}
      {!turn.live && !turn.content && (
        <p className="px-4 py-3 text-sm text-slate-500">
          {turn.stopped === "cancelled" ? "Stopped before an answer was written." : `No answer came back${turn.error ? `: ${turn.error}` : "."}`}
        </p>
      )}
      {!turn.live && (
        <div className="flex flex-wrap gap-x-3 border-t border-slate-100 px-3 py-1.5 text-[11px] text-slate-400">
          {turn.seconds != null && <span>{turn.seconds}s</span>}
          <span>{turn.steps.length === 1 ? "1 lookup" : `${turn.steps.length} lookups`}</span>
          {turn.steps.length === 0 && turn.content && (
            <span className="text-rose-600">No lookups: this answer is not from the records — treat it as unfounded.</span>
          )}
          {turn.stopped === "exhausted" && (
            <span className="text-amber-700">Cut short at the lookup limit: what had been found by then, not a complete answer.</span>
          )}
          {turn.stopped === "cancelled" && <span className="text-amber-700">Stopped.</span>}
          {turn.stopped === "failed" && <span className="text-rose-600">{turn.error}</span>}
        </div>
      )}
    </div>
  );
}

export function Ask() {
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const current = params.get("c");
  const status = useQuery({ queryKey: ["ai-status"], queryFn: aiApi.status });
  const conversations = useQuery({ queryKey: ["ask-conversations"], queryFn: aiApi.conversations });
  const [turns, setTurns] = useState<Turn[]>([]);
  // `/ask?draft=…` (from the Help pages) starts with the question typed, not sent.
  const [draft, setDraft] = useState(() => params.get("draft") ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  // Set while a turn is streaming into a conversation it created, so loading that conversation from the
  // URL does not replace the turn being written.
  const own = useRef<string | null>(null);

  const usable = status.data?.validated && status.data?.enabled;
  const workspaceId = useCurrentWorkspaceId();

  const loaded = useQuery({
    queryKey: ["ask-conversation", current],
    queryFn: () => aiApi.conversation(current!),
    enabled: !!current && own.current !== current,
  });
  const proposals = useQuery({
    queryKey: ["ask-actions", current],
    queryFn: () => aiApi.conversationActions(current!),
    enabled: !!current,
  });
  const latest = useMemo(() => new Map((proposals.data ?? []).map((a) => [a.id, a])), [proposals.data]);
  /** A turn's proposals, as they stand now: a saved turn's by its question, a streamed one's by its events. */
  const actionsOf = (t: Turn): AskAction[] =>
    t.seq != null
      ? (proposals.data ?? []).filter((a) => a.turn_seq === t.seq! - 1)
      : (t.actions ?? []).map((a) => latest.get(a.id) ?? a);
  useEffect(() => {
    if (!current) setTurns([]);
  }, [current]);
  useEffect(() => {
    if (loaded.data && own.current !== current) setTurns(loaded.data.messages.map(fromMessage));
  }, [loaded.data, current]);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [turns]);

  const remove = useMutation({
    mutationFn: (id: string) => aiApi.deleteConversation(id),
    onSuccess: (_d, id) => {
      void queryClient.invalidateQueries({ queryKey: ["ask-conversations"] });
      if (id === current) setParams({});
    },
  });

  const update = (fn: (t: Turn) => Turn) =>
    setTurns((all) => all.map((t, i) => (i === all.length - 1 && t.role === "assistant" ? fn(t) : t)));

  const onEvent = (ev: ChatEvent) => {
    switch (ev.type) {
      case "conversation":
        own.current = ev.id;
        if (ev.id !== current) setParams({ c: ev.id });
        break;
      case "thinking":
        update((t) => ({ ...t, thinking: (t.thinking + ev.text).slice(-8000) }));
        break;
      case "text":
        update((t) => ({ ...t, content: t.content + ev.text }));
        break;
      case "text_reset":
        update((t) => ({ ...t, content: "" }));
        break;
      case "step_start":
        update((t) => ({
          ...t,
          thinking: "",
          steps: [...t.steps, { tool: ev.tool, arguments: ev.arguments, result: "", error: null, seconds: 0, running: true }],
        }));
        break;
      case "step":
        update((t) => ({
          ...t,
          steps: t.steps.map((s, i) => (i === ev.index ? { ...ev, running: false } : s)),
        }));
        break;
      case "proposal":
        update((t) => ({ ...t, actions: [...(t.actions ?? []), ev.action] }));
        break;
      case "done":
        update((t) => ({
          ...t, live: false, content: ev.answer || t.content, stopped: ev.stopped, error: ev.error, seconds: ev.seconds,
          steps: t.steps.map((s) => ({ ...s, running: false })),
        }));
        break;
    }
  };

  const send = async (text: string) => {
    const question = text.trim();
    if (!question || busy) return;
    setDraft("");
    setError(null);
    setBusy(true);
    const controller = new AbortController();
    abort.current = controller;
    own.current = current;
    setTurns((all) => [
      ...all,
      { id: `u-${Date.now()}`, role: "user", content: question, steps: [], thinking: "", stopped: null, error: null, seconds: null },
      { id: `a-${Date.now()}`, role: "assistant", content: "", steps: [], thinking: "", stopped: null, error: null, seconds: null, live: true },
    ]);
    try {
      await streamChat({ question, conversation_id: current }, onEvent, controller.signal);
    } catch (e) {
      if (controller.signal.aborted) {
        update((t) => ({ ...t, live: false, stopped: "cancelled", steps: t.steps.map((s) => ({ ...s, running: false })) }));
      } else {
        setError(e instanceof ApiError ? String(e.detail ?? e.message) : e instanceof Error ? e.message : String(e));
        setTurns((all) => all.slice(0, -2));
        setDraft(question);
      }
    } finally {
      setBusy(false);
      abort.current = null;
      void queryClient.invalidateQueries({ queryKey: ["ask-conversations"] });
      void queryClient.invalidateQueries({ queryKey: ["ask-conversation"] });
      void queryClient.invalidateQueries({ queryKey: ["ask-actions"] });
    }
  };

  return (
    <div className="-m-6 flex h-[calc(100vh-3.5rem)] min-h-0">
      <aside className="flex w-64 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="p-3">
          <button
            type="button"
            onClick={() => {
              own.current = null;
              setParams({});
            }}
            disabled={busy}
            className="w-full rounded bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:bg-slate-300"
          >
            New chat
          </button>
        </div>
        <ul className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
          {(conversations.data ?? []).map((c) => (
            <li key={c.id} className="group flex items-center">
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  own.current = null;
                  setParams({ c: c.id });
                }}
                className={`min-w-0 flex-1 truncate rounded px-2 py-1.5 text-left text-sm ${
                  c.id === current ? "bg-slate-100 font-medium text-slate-900" : "text-slate-600 hover:bg-slate-50"
                }`}
                title={c.title}
              >
                {c.title}
              </button>
              <button
                type="button"
                aria-label="Delete conversation"
                disabled={busy}
                onClick={() => remove.mutate(c.id)}
                className="ml-1 hidden rounded px-1 text-xs text-slate-400 hover:bg-rose-50 hover:text-rose-600 group-hover:block"
              >
                ✕
              </button>
            </li>
          ))}
          {conversations.data?.length === 0 && <li className="px-2 py-1 text-xs text-slate-400">No conversations yet.</li>}
        </ul>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col bg-slate-50">
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto flex max-w-3xl flex-col gap-4 p-6">
            {turns.length === 0 && (
              <header>
                <h1 className="text-lg font-semibold text-slate-900">Ask ARGUS</h1>
                <p className="mt-1 text-sm text-slate-600">
                  Answers come only from this workspace's records — objects, tickets and documentation — and
                  every lookup is shown as it runs. Ask a follow-up to continue the conversation.
                </p>
                {status.isSuccess && !usable && (
                  <div className="mt-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                    {status.data?.reason ?? "AI features are not available in this workspace."}{" "}
                    <Link className="underline" to={workspaceId ? `/workspaces/${workspaceId}/ai` : "/"}>
                      Configure the AI endpoint
                    </Link>
                  </div>
                )}
                <div className="mt-4 flex flex-wrap gap-2">
                  {STARTERS.map((q) => (
                    <button
                      key={q}
                      type="button"
                      disabled={!usable || busy}
                      onClick={() => void send(q)}
                      className="rounded-full border border-slate-300 bg-white px-3 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </header>
            )}
            {loaded.isLoading && <p className="text-sm text-slate-400">Loading the conversation…</p>}
            {turns.map((t) =>
              t.role === "user" ? (
                <div key={t.id} className="self-end whitespace-pre-wrap rounded-lg bg-slate-900 px-3 py-2 text-sm text-white">
                  {t.content}
                </div>
              ) : (
                <AssistantTurn key={t.id} turn={t} actions={actionsOf(t)} conversationId={current} />
              ),
            )}
            <div ref={bottom} />
          </div>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            void send(draft);
          }}
          className="border-t border-slate-200 bg-white p-3"
        >
          <div className="mx-auto flex max-w-3xl items-end gap-2">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send(draft);
                }
              }}
              rows={Math.min(6, Math.max(1, draft.split("\n").length))}
              placeholder={turns.length ? "Ask a follow-up…" : "What has gone wrong with this magnet before?"}
              disabled={!usable}
              className="min-h-[2.5rem] flex-1 resize-none rounded border border-slate-300 px-3 py-2 text-sm disabled:bg-slate-50"
            />
            {busy ? (
              <button
                type="button"
                onClick={() => abort.current?.abort()}
                className="rounded border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50"
              >
                Stop
              </button>
            ) : (
              <button
                type="submit"
                disabled={!usable || !draft.trim()}
                className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:bg-slate-300"
              >
                Send
              </button>
            )}
          </div>
          {error && <p className="mx-auto mt-2 max-w-3xl text-sm text-rose-700">{error}</p>}
          <p className="mx-auto mt-1 max-w-3xl text-[11px] text-slate-400">
            Enter to send · Shift+Enter for a new line · keys in answers open their records
          </p>
        </form>
      </section>
    </div>
  );
}
