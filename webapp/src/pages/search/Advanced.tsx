import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { jqlApi, type JqlEntity, type JqlResult } from "../../api/client";
import { useShowKeys } from "../../api/displayPrefs";
import { openInWorkspace } from "../../api/session";
import { useCurrentWorkspaceId } from "../../api/useCurrentWorkspaceId";

const ENTITIES: { id: JqlEntity; label: string }[] = [
  { id: "tickets", label: "Tickets" },
  { id: "assets", label: "Equipment" },
  { id: "documents", label: "Documents" },
];

const EXAMPLES: Record<JqlEntity, string[]> = {
  tickets: [
    "assignee = currentUser() AND statusCategory != Done ORDER BY priority DESC",
    "created >= -7d ORDER BY created DESC",
    'text ~ "vacuum leak" AND status != closed',
    "project in (sparc, eli) AND priority in (High, Highest)",
    "equipment = SPARC-IP-01",
  ],
  assets: [
    'type = "Ion Pump" ORDER BY key',
    "label = LNFMAC-128463",
    "serial ~ VPI AND updated >= startOfMonth()",
    "status = Retired",
    "voltage_max > 100",
  ],
  documents: [
    "status = published ORDER BY updated DESC",
    "status in (draft, in_review)",
    "text ~ bakeout",
    "type = Procedure AND updated >= -30d",
  ],
};

const RECENT = "argus.jql.recent";

function recent(): string[] {
  try {
    return JSON.parse(localStorage.getItem(RECENT) ?? "[]");
  } catch {
    return [];
  }
}

function remember(entity: JqlEntity, jql: string) {
  try {
    const key = `${entity}\u0000${jql}`;
    const list = [key, ...recent().filter((k) => k !== key)].slice(0, 10);
    localStorage.setItem(RECENT, JSON.stringify(list));
  } catch {
    // storage unavailable: nothing is remembered
  }
}

const PAGE = 50;

/** Advanced query over tickets, equipment and documents. The query is in the
 *  address, so a search can be bookmarked or sent to a colleague. */
export function AdvancedSearch() {
  const [params, setParams] = useSearchParams();
  const entity = (params.get("entity") as JqlEntity) || "tickets";
  const jql = params.get("jql") ?? "";
  const offset = Number(params.get("offset") ?? 0);
  const [draft, setDraft] = useState(jql);
  const [showFields, setShowFields] = useState(false);
  const showKeys = useShowKeys();
  const here = useCurrentWorkspaceId();

  useEffect(() => setDraft(jql), [jql]);

  const result = useQuery<JqlResult, Error>({
    queryKey: ["jql", entity, jql, offset],
    queryFn: () => jqlApi.search(entity, jql, PAGE, offset),
    enabled: params.has("jql"),
    retry: false,
  });
  const fields = useQuery({ queryKey: ["jql-fields"], queryFn: jqlApi.fields, enabled: showFields, staleTime: Infinity });

  const run = (text = draft, e: JqlEntity = entity) => {
    remember(e, text);
    setParams({ entity: e, jql: text });
  };

  const err = result.error as (Error & { detail?: { error?: string; position?: number | null } }) | null;
  const position = err?.detail?.position ?? null;

  return (
    <div className="max-w-6xl space-y-4">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Advanced query</h1>
        <p className="mt-1 text-sm text-slate-500">
          Fields, operators and functions, written as Jira's searches are, so a query copied from Jira works here.
          Without <code>project = …</code> a query searches this workspace and what is shared with every workspace.
        </p>
      </div>

      <div className="flex rounded border border-slate-300 text-sm w-fit">
        {ENTITIES.map((x) => (
          <button key={x.id} type="button" onClick={() => setParams({ entity: x.id, ...(jql ? { jql } : {}) })}
                  className={`px-3 py-1.5 ${entity === x.id ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-50"}`}>
            {x.label}
          </button>
        ))}
      </div>

      <form onSubmit={(e) => { e.preventDefault(); run(); }} className="space-y-2">
        <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={3} spellCheck={false}
                  onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); run(); } }}
                  placeholder={EXAMPLES[entity][0]}
                  className={`w-full rounded border px-3 py-2 font-mono text-sm ${err ? "border-red-400" : "border-slate-300"}`} />
        {err && (
          <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
            {err.detail?.error ?? err.message}
            {position != null && (
              <pre className="mt-1 overflow-x-auto font-mono text-xs text-red-900">
                {jql}
                {"\n"}
                {" ".repeat(position)}^
              </pre>
            )}
          </div>
        )}
        <div className="flex items-center gap-3">
          <button type="submit" className="rounded bg-slate-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-slate-800">
            Search
          </button>
          <span className="text-xs text-slate-400">Ctrl/⌘ + Enter</span>
          <button type="button" onClick={() => setShowFields(!showFields)} className="ml-auto text-xs text-indigo-700 hover:underline">
            {showFields ? "Hide" : "Show"} fields and syntax
          </button>
        </div>
      </form>

      {showFields && (
        <div className="grid gap-4 rounded border border-slate-200 bg-white p-4 text-sm md:grid-cols-2">
          <div>
            <h2 className="mb-2 font-semibold text-slate-900">Fields of {ENTITIES.find((x) => x.id === entity)?.label.toLowerCase()}</h2>
            <ul className="space-y-0.5">
              {(fields.data?.[entity] ?? []).map((f) => (
                <li key={f.field}><code className="text-indigo-800">{f.field}</code> <span className="text-slate-500">— {f.help}</span></li>
              ))}
              <li className="text-slate-500">Any other name is an attribute: <code>serial</code>, <code>cf[voltage_max]</code>, <code>"Field name"</code>.</li>
            </ul>
          </div>
          <div className="space-y-1 text-slate-600">
            <h2 className="mb-2 font-semibold text-slate-900">Syntax</h2>
            <p><code>= != ~ !~ &gt; &gt;= &lt; &lt;=</code>, <code>IN (a, b)</code>, <code>NOT IN</code>, <code>IS EMPTY</code>, <code>IS NOT EMPTY</code></p>
            <p><code>AND</code>, <code>OR</code>, <code>NOT</code>, parentheses, then <code>ORDER BY field ASC|DESC, …</code></p>
            <p>Dates: <code>2026-10-01</code>, <code>"2026-10-01 14:00"</code>, <code>-7d</code>, <code>-2w</code>, <code>-4h</code></p>
            <p>Functions: <code>currentUser()</code>, <code>now()</code>, <code>startOfDay(-1)</code>, <code>endOfWeek()</code>, <code>startOfMonth("-1M")</code>, <code>startOfYear()</code></p>
            <p><code>~</code> contains every word; <code>text ~</code> searches everything written.</p>
          </div>
        </div>
      )}

      {!params.has("jql") && (
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <h2 className="mb-1 text-sm font-semibold text-slate-900">Examples</h2>
            <ul className="space-y-1">
              {EXAMPLES[entity].map((x) => (
                <li key={x}><button type="button" onClick={() => run(x)} className="text-left font-mono text-xs text-indigo-700 hover:underline">{x}</button></li>
              ))}
            </ul>
          </div>
          {recent().length > 0 && (
            <div>
              <h2 className="mb-1 text-sm font-semibold text-slate-900">Recent</h2>
              <ul className="space-y-1">
                {recent().map((k) => {
                  const [e, q] = k.split("\u0000") as [JqlEntity, string];
                  return (
                    <li key={k}>
                      <button type="button" onClick={() => run(q, e)} className="text-left font-mono text-xs text-indigo-700 hover:underline">
                        <span className="mr-1 text-slate-400">{e}:</span>{q || "(everything)"}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </div>
      )}

      {result.isFetching && <p className="text-sm text-slate-500">Searching…</p>}
      {result.data && (
        <div className="rounded border border-slate-200 bg-white">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2 text-sm">
            <span className="font-medium text-slate-900">
              {result.data.capped ? "At least " : ""}{result.data.total} found
            </span>
            {result.data.total > PAGE && (
              <span className="flex items-center gap-2 text-xs">
                <button type="button" disabled={offset === 0}
                        onClick={() => setParams({ entity, jql, offset: String(Math.max(0, offset - PAGE)) })}
                        className="rounded border border-slate-300 px-2 py-0.5 disabled:opacity-40">‹</button>
                {offset + 1}–{Math.min(offset + PAGE, result.data.total)}
                <button type="button" disabled={offset + PAGE >= result.data.total}
                        onClick={() => setParams({ entity, jql, offset: String(offset + PAGE) })}
                        className="rounded border border-slate-300 px-2 py-0.5 disabled:opacity-40">›</button>
              </span>
            )}
          </div>
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                {showKeys && <th className="px-4 py-2">{entity === "documents" ? "Code" : "Key"}</th>}
                <th className="px-4 py-2">{entity === "assets" ? "Name" : "Title"}</th>
                <th className="px-4 py-2">{entity === "assets" ? "Type" : "State"}</th>
                {entity === "tickets" && <th className="px-4 py-2">Priority</th>}
                <th className="px-4 py-2">Workspace</th>
                <th className="px-4 py-2">Updated</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {result.data.items.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-4 text-slate-500">Nothing matches.</td></tr>
              )}
              {result.data.items.map((i) => {
                const path = entity === "tickets" ? `/tickets/${i.uid}` : entity === "assets" ? `/assets/${i.uid}` : `/documents/${i.uid}`;
                const key = entity === "tickets" ? i.source_key ?? "" : entity === "assets" ? i.key : i.code;
                return (
                  <tr key={i.uid} className="hover:bg-slate-50">
                    {showKeys && <td className="px-4 py-2 font-mono text-xs text-slate-500">{key}</td>}
                    <td className="px-4 py-2 font-medium text-slate-900">
                      {/* A record of another workspace opens there. */}
                      <Link to={path} className="hover:underline"
                            onClick={(e) => { if (openInWorkspace(i.workspace_id, path, here)) e.preventDefault(); }}>
                        {i.title ?? i.name}
                      </Link>
                    </td>
                    <td className="px-4 py-2 text-slate-500">{entity === "assets" ? i.type : i.state}</td>
                    {entity === "tickets" && <td className="px-4 py-2 text-slate-500">{i.priority}</td>}
                    <td className="px-4 py-2 text-slate-500">{i.workspace_name ?? i.workspace_id}</td>
                    <td className="px-4 py-2 text-slate-500">{i.updated_at ? new Date(i.updated_at).toLocaleDateString() : ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
