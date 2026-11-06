import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { assetsApi, documentsApi, graphApi, issuesApi } from "../../api/client";
import type { FailureNode, FailureStep, ImpactResult, RootCauseCandidate } from "../../api/types";
import { GraphCanvas, IN, OUT } from "../../components/graph/GraphCanvas";
import { KIND_STYLE, LAYER_STYLE, LOSS_LABEL, nodeId, place, bundleEdges, openBundle, STEP, type GEdge, type GNode, type Neighbour } from "../../components/graph/model";
import { useBranches } from "../../components/graph/useBranches";
import { DirectionLegend, RelationList } from "../../components/RelationGraph";

/** The knowledge graph, three ways.
 *
 * Explore: start from any object, ticket or document; what points at a node is drawn to its left, what it
 * points at to its right, and double-clicking a node opens its branches (many neighbours of one kind arrive
 * as one group). Impact: this fails — what stops with it, what it loses, and by which path. Root cause:
 * these misbehave — what would explain them, ranked, with the path from each candidate to each symptom.
 * Impact and root cause follow how a failure travels along each relation (services/causal_model.py). */

const START_KINDS = [
  { kind: "asset", label: "Object" },
  { kind: "ticket", label: "Ticket" },
  { kind: "document", label: "Document" },
] as const;
type StartKind = (typeof START_KINDS)[number]["kind"];
type Mode = "explore" | "impact" | "rootcause";

const LAYERS = ["power", "cooling", "vacuum", "control", "timing", "interlock", "function", "composition", "membership", "beam", "environment"];

function detailPath(n: { kind: string; uid: string; restricted?: boolean }): string | null {
  // A root-cause step known only by its key (keys have colons, uids do not) has no page to open from here.
  if (n.restricted || n.uid.includes(":")) return null;
  if (n.kind === "asset") return `/assets/${n.uid}`;
  if (n.kind === "ticket") return `/tickets/${n.uid}`;
  if (n.kind === "document") return `/documents/${n.uid}`;
  return null;
}

function truncate(text: string, max: number) {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/** The losses an affected object suffers, worst first. */
function lossOf(losses: Record<string, number>): string {
  for (const k of ["function", "permit", "control"]) if (losses[k]) return LOSS_LABEL[k];
  return Object.keys(losses)[0] ?? "";
}

/** Impact as a graph: the failed object, then each affected one a column per hop, joined by the last step of
 *  its path. Leaves of one type from one parent are grouped. */
function impactGraph(result: ImpactResult) {
  const seq = { current: 0 };
  const byKey = new Map<string, FailureNode>([[result.origin.key, result.origin], ...result.affected.map((a) => [a.key, a] as const)]);
  const id = (key: string) => nodeId("asset", byKey.get(key)?.uid ?? key);
  const origin: GNode = { id: nodeId("asset", result.origin.uid), kind: "asset", uid: result.origin.uid, label: result.origin.name,
                          sub: result.origin.type, col: 0, y: 0, parent: null, seq: seq.current++, mark: "origin" };
  const nodes = new Map<string, GNode>([[origin.id, origin]]);
  const edges: GEdge[] = [];
  const children = new Map<string, Neighbour[]>();
  const hasChildren = new Set(result.affected.map((a) => a.path[a.path.length - 1]?.provider).filter(Boolean).map((k) => id(k!)));
  for (const a of [...result.affected].sort((x, y) => x.depth - y.depth)) {
    const step = a.path[a.path.length - 1];
    if (!step) continue;
    const parent = id(step.provider);
    const edge: GEdge = { from: parent, to: nodeId("asset", a.uid), relation: step.relation, via: step.layer };
    children.set(parent, [...(children.get(parent) ?? []), {
      node: { id: edge.to, kind: "asset", uid: a.uid, label: a.name, sub: a.type, mark: "affected", loss: lossOf(a.losses) },
      edge,
    }]);
  }
  // Breadth first, so a parent is placed before its children.
  const queue = [origin.id];
  while (queue.length) {
    const pid = queue.shift()!;
    const parent = nodes.get(pid);
    const kids = children.get(pid) ?? [];
    if (!parent || !kids.length) continue;
    const inner = kids.filter((k) => hasChildren.has(k.node.id));
    const leaves = kids.filter((k) => !hasChildren.has(k.node.id));
    for (const [list, grouping] of [[inner, false], [leaves, true]] as const) {
      for (const n of place(nodes, parent, parent.col + 1, list, seq, grouping)) {
        nodes.set(n.id, n);
        if (n.bundle) edges.push(...bundleEdges(n));
        else queue.push(n.id);
      }
    }
    edges.push(...kids.filter((k) => nodes.has(k.node.id)).map((k) => k.edge));
  }
  return { nodes, edges };
}

/** One candidate cause and its paths to the symptoms it explains: the cause, then one column per step. */
function causeGraph(c: RootCauseCandidate, symptoms: FailureNode[]) {
  const seq = { current: 0 };
  const names = new Map<string, FailureNode>([[c.key, c], ...symptoms.map((s) => [s.key, s] as const), ...c.explains.map((e) => [e.key, e] as const)]);
  const symptomKeys = new Set(symptoms.map((s) => s.key));
  const nodes = new Map<string, GNode>();
  const edges: GEdge[] = [];
  const idOf = (key: string) => nodeId("asset", names.get(key)?.uid ?? key);
  const put = (key: string, col: number, parent: string | null) => {
    const id = idOf(key);
    if (nodes.has(id)) return nodes.get(id)!;
    const known = names.get(key);
    const taken = [...nodes.values()].filter((n) => n.col === col).length;
    // A step in the middle of a path is known only by its key (SPARC-IOC-vac-gunvpc): its last part reads as a name.
    const n: GNode = { id, kind: "asset", uid: known?.uid ?? key, label: known?.name ?? key.replace(/^[^-:]+[-:][A-Z]+[-:]/, ""),
                       sub: known?.type ?? (known ? null : key),
                       col, y: taken * 58, parent, seq: seq.current++,
                       mark: key === c.key ? "cause" : symptomKeys.has(key) ? "symptom" : undefined };
    nodes.set(id, n);
    return n;
  };
  put(c.key, 0, null);
  for (const e of c.explains) {
    e.path.forEach((step: FailureStep, i: number) => {
      const from = put(step.provider, i, null);
      const to = put(step.dependent, i + 1, from.id);
      edges.push({ from: from.id, to: to.id, relation: step.relation, via: step.layer });
    });
  }
  return { nodes, edges };
}

function StartPicker({
  kind,
  value,
  onPick,
  placeholder,
}: {
  kind: StartKind;
  placeholder?: string;
  value: { label: string } | null;
  onPick: (uid: string, label: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  const assets = useQuery({
    queryKey: ["assets"],
    queryFn: () => assetsApi.list(),
    enabled: kind === "asset",
  });
  const issues = useQuery({
    queryKey: ["issues"],
    queryFn: () => issuesApi.list(),
    enabled: kind === "ticket",
  });
  const documents = useQuery({
    queryKey: ["documents"],
    queryFn: () => documentsApi.list(),
    enabled: kind === "document",
  });

  const options = useMemo(() => {
    if (kind === "asset")
      return (assets.data ?? []).map((a) => ({ uid: a.uid, label: a.name, sub: a.key }));
    if (kind === "ticket")
      return (issues.data ?? []).map((i) => ({
        uid: i.uid,
        label: i.title,
        sub: (i.attributes?.argus_source_key as string) ?? "",
      }));
    return (documents.data ?? []).map((d) => ({ uid: d.uid, label: d.title, sub: d.code }));
  }, [kind, assets.data, issues.data, documents.data]);

  const loading = assets.isLoading || issues.isLoading || documents.isLoading;

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q
      ? options.filter(
          (o) => o.label.toLowerCase().includes(q) || o.sub.toLowerCase().includes(q),
        )
      : options;
    return filtered.slice(0, 40);
  }, [options, query]);

  return (
    <div className="relative">
      <input
        value={open ? query : value ? value.label : ""}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => {
          setQuery("");
          setOpen(true);
        }}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder={loading ? "Loading…" : placeholder ?? `Search ${kind}s…`}
        className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
      />
      {open && (
        <div className="absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded border border-slate-200 bg-white shadow-lg">
          {matches.length === 0 && (
            <p className="px-2 py-2 text-xs text-slate-400">
              {loading ? "Loading…" : "Nothing matches"}
            </p>
          )}
          {matches.map((o) => (
            <button
              type="button"
              key={o.uid}
              onMouseDown={(e) => {
                e.preventDefault();
                onPick(o.uid, o.label);
                setOpen(false);
              }}
              className="block w-full px-2 py-1.5 text-left text-sm hover:bg-slate-50"
            >
              <span className="text-slate-800">{truncate(o.label, 48)}</span>
              {o.sub && <span className="ml-2 text-xs text-slate-400">{o.sub}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}


export function GraphExplorer() {
  const [mode, setMode] = useState<Mode>("explore");
  const [startKind, setStartKind] = useState<StartKind>("asset");
  const [start, setStart] = useState<{ uid: string; label: string } | null>(null);
  const [kinds, setKinds] = useState<string[]>([]);
  const [layers, setLayers] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [symptoms, setSymptoms] = useState<{ uid: string; label: string }[]>([]);
  const [healthy, setHealthy] = useState<{ uid: string; label: string }[]>([]);
  const [candidate, setCandidate] = useState(0);
  const [opened, setOpened] = useState<Set<string>>(new Set());   // groups opened in an analysis view
  const [byMeaning, setByMeaning] = useState(false);              // the semantic graph beside the relations

  const summary = useQuery({ queryKey: ["graph-summary"], queryFn: graphApi.summary });
  const explore = useBranches(mode === "explore" && start ? { kind: startKind, uid: start.uid } : null,
                              kinds.length ? kinds : undefined);
  const impact = useQuery({
    queryKey: ["impact", start?.uid, layers.join(",")],
    queryFn: () => graphApi.impact(start!.uid, layers.length ? layers : undefined),
    enabled: mode === "impact" && !!start && startKind === "asset",
  });
  const rootCause = useQuery({
    queryKey: ["root-cause", symptoms.map((s) => s.uid).join(","), healthy.map((h) => h.uid).join(","), layers.join(",")],
    queryFn: () => graphApi.rootCause({ symptoms: symptoms.map((s) => s.uid), healthy: healthy.map((h) => h.uid),
                                        layers: layers.length ? layers : undefined, top: 10 }),
    enabled: false,
  });

  // What is drawn.
  const analysis = useMemo(() => {
    if (mode === "impact" && impact.data) return impactGraph(impact.data);
    if (mode === "rootcause" && rootCause.data?.candidates[candidate])
      return causeGraph(rootCause.data.candidates[candidate], rootCause.data.symptoms);
    return null;
  }, [mode, impact.data, rootCause.data, candidate]);
  const semantic = useQuery({
    queryKey: ["semantic", startKind, start?.uid],
    queryFn: () => graphApi.semantic(startKind, start!.uid),
    enabled: mode === "explore" && !!start && byMeaning,
    staleTime: 60_000,
  });

  const drawn = useMemo(() => {
    if (mode === "explore") {
      if (!byMeaning || !semantic.data || !explore.rootId) {
        return { nodes: explore.nodes, edges: explore.edges, rootId: explore.rootId };
      }
      // Related by meaning: a column of their own, right of everything drawn, joined to the start by dashed lines.
      const nodes = new Map(explore.nodes);
      const col = Math.max(0, ...[...explore.nodes.values()].map((n) => n.col)) + 1;
      const fresh = semantic.data.edges.filter((e) => !nodes.has(nodeId(e.to_kind, e.to_uid)));
      fresh.forEach((e, i) => {
        const n = semantic.data!.nodes.find((x) => x.kind === e.to_kind && x.uid === e.to_uid);
        nodes.set(nodeId(e.to_kind, e.to_uid), {
          id: nodeId(e.to_kind, e.to_uid), kind: e.to_kind as GNode["kind"], uid: e.to_uid, label: n?.label ?? e.to_uid,
          sub: n?.sublabel ?? null, col, y: (i - (fresh.length - 1) / 2) * STEP, parent: explore.rootId, seq: 10_000 + i,
        });
      });
      const edges = [...explore.edges, ...semantic.data.edges.map((e): GEdge => ({
        from: explore.rootId!, to: nodeId(e.to_kind, e.to_uid), relation: e.score.toFixed(2), via: "semantic",
      }))];
      return { nodes, edges, rootId: explore.rootId };
    }
    if (!analysis) return { nodes: new Map<string, GNode>(), edges: [] as GEdge[], rootId: null };
    // Groups the person opened in this view, replaced by their members.
    const nodes = new Map(analysis.nodes);
    let edges = analysis.edges;
    for (const gid of opened) {
      const group = nodes.get(gid);
      if (!group?.bundle) continue;
      const { nodes: ms, edges: es } = openBundle(nodes, group, { current: 0 });
      nodes.delete(gid);
      for (const m of ms) nodes.set(m.id, { ...m, mark: "affected" });
      edges = [...edges.filter((e) => e.from !== gid && e.to !== gid), ...es];
    }
    const root = [...nodes.values()].find((n) => n.mark === "origin" || n.mark === "cause");
    return { nodes, edges, rootId: root?.id ?? null };
  }, [mode, explore.nodes, explore.edges, explore.rootId, analysis, opened, byMeaning, semantic.data]);

  const current = selected && drawn.nodes.has(selected) ? selected : drawn.rootId;
  const sel = current ? drawn.nodes.get(current) : undefined;
  const name = (id: string) => drawn.nodes.get(id)?.label ?? id;
  const affected = impact.data?.affected.find((a) => sel && a.uid === sel.uid);

  const go = (m: Mode) => {
    setMode(m);
    setSelected(null);
    setOpened(new Set());
  };
  const openNode = (n: GNode) => {
    if (mode === "explore") return explore.toggle(n);
    if (n.bundle) setOpened((o) => new Set(o).add(n.id));
  };
  const addSymptom = (uid: string, label: string) => setSymptoms((s) => (s.some((x) => x.uid === uid) ? s : [...s, { uid, label }]));

  return (
    <div className="-m-6 flex h-[calc(100vh-3.5rem)] min-h-0 flex-col">
      <div className="border-b border-slate-200 bg-white px-6 py-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h1 className="text-xl font-semibold text-slate-900">Knowledge graph</h1>
          {summary.data && (
            <p className="text-xs text-slate-500">
              {summary.data.nodes.assets} objects · {summary.data.nodes.tickets} tickets · {summary.data.nodes.documents} documents ·{" "}
              {Object.values(summary.data.edges).reduce((a, b) => a + b, 0)} connections
            </p>
          )}
        </div>
        <div className="mt-2 flex flex-wrap items-end gap-3">
          <div className="flex rounded border border-slate-300 text-sm">
            {([["explore", "Explore"], ["impact", "Impact"], ["rootcause", "Root cause"]] as const).map(([m, label]) => (
              <button key={m} type="button" onClick={() => go(m)}
                      className={`px-3 py-1.5 ${mode === m ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-50"}`}>
                {label}
              </button>
            ))}
          </div>

          {mode !== "rootcause" && (
            <>
              {mode === "explore" && (
                <select value={startKind} onChange={(e) => { setStartKind(e.target.value as StartKind); setStart(null); }}
                        className="rounded border border-slate-300 px-2 py-1.5 text-sm">
                  {START_KINDS.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}
                </select>
              )}
              <div className="w-80">
                <StartPicker kind={mode === "impact" ? "asset" : startKind} value={start}
                             placeholder={mode === "impact" ? "What fails? Search objects…" : undefined}
                             onPick={(uid, label) => { if (mode === "impact") setStartKind("asset"); setStart({ uid, label }); setSelected(null); setOpened(new Set()); }} />
              </div>
            </>
          )}

          {mode === "rootcause" && (
            <div className="flex flex-wrap items-center gap-2">
              <div className="w-64">
                <StartPicker kind="asset" value={null} placeholder="Add what misbehaves…" onPick={addSymptom} />
              </div>
              <div className="w-56">
                <StartPicker kind="asset" value={null} placeholder="Add what still works…"
                             onPick={(uid, label) => setHealthy((h) => (h.some((x) => x.uid === uid) ? h : [...h, { uid, label }]))} />
              </div>
              <button type="button" disabled={!symptoms.length || rootCause.isFetching}
                      onClick={() => { setCandidate(0); setSelected(null); setOpened(new Set()); void rootCause.refetch(); }}
                      className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:bg-slate-300">
                {rootCause.isFetching ? "Working it out…" : "Find causes"}
              </button>
            </div>
          )}

          {mode === "explore" ? (
            <div className="flex flex-wrap gap-1">
              {["asset", "ticket", "document", "group", "person"].map((k) => {
                const style = KIND_STYLE[k];
                const on = kinds.length === 0 || kinds.includes(k);
                return (
                  <button key={k} type="button"
                          onClick={() => setKinds((cur) => {
                            const base = cur.length === 0 ? ["asset", "ticket", "document", "group", "person"] : cur;
                            const next = base.includes(k) ? base.filter((x) => x !== k) : [...base, k];
                            return next.length === 5 ? [] : next;
                          })}
                          className={`rounded-full border px-2.5 py-1 text-xs ${on ? "text-slate-700" : "text-slate-300"}`}
                          style={{ borderColor: on ? style.stroke : "#e2e8f0", background: on ? style.fill : "#fff" }}>
                    {style.label}
                  </button>
                );
              })}
              <label className="ml-2 flex items-center gap-1 text-xs text-teal-700"
                     title="From the knowledge index: records whose written knowledge is about the same thing as the start">
                <input type="checkbox" checked={byMeaning} onChange={(e) => setByMeaning(e.target.checked)} />
                related by meaning
                {byMeaning && semantic.isFetching && " …"}
                {byMeaning && semantic.data && !semantic.data.available && (
                  <span className="text-slate-400"> — {semantic.data.reason}</span>
                )}
                {byMeaning && semantic.data?.available && semantic.data.edges.length === 0 && (
                  <span className="text-slate-400"> — none found</span>
                )}
              </label>
            </div>
          ) : (
            <div className="flex flex-wrap gap-1" title="Which ways a failure may travel; none selected means all">
              {LAYERS.map((l) => {
                const on = layers.length === 0 || layers.includes(l);
                return (
                  <button key={l} type="button"
                          onClick={() => setLayers((cur) => {
                            const base = cur.length === 0 ? LAYERS : cur;
                            const next = base.includes(l) ? base.filter((x) => x !== l) : [...base, l];
                            return next.length === LAYERS.length ? [] : next;
                          })}
                          className={`rounded-full border px-2 py-0.5 text-[11px] ${on ? "text-slate-700" : "text-slate-300"}`}
                          style={{ borderColor: on ? LAYER_STYLE[l] : "#e2e8f0" }}>
                    {l}
                  </button>
                );
              })}
            </div>
          )}
        </div>
        {mode === "rootcause" && (symptoms.length > 0 || healthy.length > 0) && (
          <div className="mt-2 flex flex-wrap gap-1 text-xs">
            {symptoms.map((s) => (
              <span key={s.uid} className="rounded-full border border-red-300 bg-red-50 px-2 py-0.5 text-red-800">
                ✕ {s.label} <button onClick={() => setSymptoms((x) => x.filter((y) => y.uid !== s.uid))} className="ml-1 text-red-400">×</button>
              </span>
            ))}
            {healthy.map((s) => (
              <span key={s.uid} className="rounded-full border border-emerald-300 bg-emerald-50 px-2 py-0.5 text-emerald-800">
                ✓ {s.label} <button onClick={() => setHealthy((x) => x.filter((y) => y.uid !== s.uid))} className="ml-1 text-emerald-400">×</button>
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="relative min-w-0 flex-1">
          {mode === "explore" && !start && <Hint>Pick an object, ticket or document to see what points at it and what it points at.</Hint>}
          {mode === "impact" && !start && <Hint>Pick an object: everything that stops when it fails is drawn, with what it loses and the path.</Hint>}
          {mode === "rootcause" && !rootCause.data && <Hint>Add what misbehaves (and, if you know, what still works), then Find causes.</Hint>}
          {mode === "impact" && impact.isFetching && <Hint>Working out what depends on it…</Hint>}
          {mode === "impact" && impact.data && impact.data.count === 0 && <Hint>Nothing depends on it along the selected layers.</Hint>}
          {mode === "rootcause" && rootCause.data && rootCause.data.candidates.length === 0 && <Hint>No candidate explains these symptoms along the selected layers.</Hint>}
          {explore.error && mode === "explore" && <Hint>{explore.error}</Hint>}
          {drawn.nodes.size > 0 && (
            <GraphCanvas nodes={drawn.nodes} edges={drawn.edges} rootId={drawn.rootId} selected={current}
                         onSelect={setSelected} onOpen={openNode} colouring={mode === "explore" ? "direction" : "layer"}
                         expandable={mode === "explore"}
                         fitKey={mode === "rootcause" ? `${candidate}:${rootCause.dataUpdatedAt}` : undefined}
                         open={mode === "explore" ? explore.open : undefined} loading={mode === "explore" ? explore.loading : undefined} />
          )}
        </div>

        <aside className="w-80 shrink-0 overflow-y-auto border-l border-slate-200 bg-white p-3 text-sm">
          <div className="mb-3 text-xs text-slate-500">
            {mode === "explore" ? <DirectionLegend /> : <LayerLegend edges={drawn.edges} />}
          </div>

          {mode === "impact" && impact.data && (
            <div className="mb-3 rounded border border-red-200 bg-red-50 p-2 text-xs text-red-900">
              If <b>{impact.data.origin.name}</b> fails, <b>{impact.data.count}</b> objects are affected
              {Object.keys(impact.data.by_loss).length > 0 && ": "}
              {Object.entries(impact.data.by_loss).map(([k, v]) => `${v} ${LOSS_LABEL[k] ?? k}`).join(", ")}.
              <ul className="mt-1 text-red-800">
                {Object.entries(impact.data.by_type).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([t, n]) => <li key={t}>{n} × {t}</li>)}
              </ul>
              {impact.data.truncated && <p className="mt-1 text-amber-800">Cut short: there is more than shown.</p>}
            </div>
          )}

          {mode === "rootcause" && rootCause.data && (
            <div className="mb-3">
              {rootCause.data.hypotheses[0] && (
                <p className="mb-2 rounded bg-amber-50 p-2 text-xs text-amber-900">
                  Fewest causes that explain everything:{" "}
                  {rootCause.data.hypotheses[0].causes.map((c) => c.name).join(" + ")}
                  {rootCause.data.hypotheses[0].unexplained.length > 0 && ` (still unexplained: ${rootCause.data.hypotheses[0].unexplained.join(", ")})`}
                </p>
              )}
              <ol className="space-y-1">
                {rootCause.data.candidates.map((c, i) => (
                  <li key={c.uid}>
                    <button type="button" onClick={() => { setCandidate(i); setSelected(null); setOpened(new Set()); }}
                            className={`w-full rounded px-2 py-1 text-left text-xs ${i === candidate ? "bg-slate-900 text-white" : "hover:bg-slate-50"}`}>
                      <span className="font-medium">{i + 1}. {c.name}</span>{" "}
                      <span className={i === candidate ? "text-slate-300" : "text-slate-500"}>
                        {c.type} · fit {Math.round(c.fit * 100)}% · explains {c.explains.length}/{rootCause.data!.symptoms.length}
                        {c.would_also_affect ? ` · would also affect ${c.would_also_affect}` : ""}
                        {c.history.tickets ? ` · ${c.history.tickets} past tickets` : ""}
                        {c.contradicted_by.length ? " · contradicted" : ""}
                      </span>
                    </button>
                  </li>
                ))}
              </ol>
              {rootCause.data.not_found.length > 0 && <p className="mt-1 text-xs text-slate-400">Not found: {rootCause.data.not_found.join(", ")}</p>}
            </div>
          )}

          {sel && (
            <div className="border-t border-slate-100 pt-3">
              <div className="font-semibold text-slate-900">{sel.restricted ? "Restricted" : sel.label}</div>
              <div className="text-xs text-slate-500">{sel.bundle ? `grouped by “${sel.sub}”` : sel.sub}{sel.loss ? ` · ${sel.loss}` : ""}</div>
              <div className="mt-2 flex flex-wrap gap-1">
                {sel.bundle ? (
                  <Btn onClick={() => openNode(sel)}>Show all {sel.bundle.members.length}</Btn>
                ) : (
                  <>
                    {detailPath(sel) && <Link to={detailPath(sel)!} className="rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50">Open</Link>}
                    {mode === "explore" && !sel.restricted && <Btn onClick={() => explore.toggle(sel)}>{explore.open.has(sel.id) ? "Fold branches" : "Open branches"}</Btn>}
                    {mode === "explore" && sel.id !== drawn.rootId && ["asset", "ticket", "document"].includes(sel.kind) && (
                      <Btn onClick={() => { setStartKind(sel.kind as StartKind); setStart({ uid: sel.uid, label: sel.label }); setSelected(null); }}>Centre here</Btn>
                    )}
                    {sel.kind === "asset" && !sel.restricted && mode !== "impact" && (
                      <Btn onClick={() => { setStartKind("asset"); setStart({ uid: sel.uid, label: sel.label }); go("impact"); }}>What stops if it fails?</Btn>
                    )}
                    {sel.kind === "asset" && !sel.restricted && (
                      <Btn onClick={() => { addSymptom(sel.uid, sel.label); go("rootcause"); }}>It misbehaves: find causes</Btn>
                    )}
                  </>
                )}
              </div>
              {mode === "explore" && !sel.bundle && (
                <>
                  <RelationList title="Inbound" color={IN} edges={drawn.edges.filter((e) => e.to === sel.id && drawn.nodes.has(e.from))} side="in" name={name} onPick={setSelected} />
                  <RelationList title="Outbound" color={OUT} edges={drawn.edges.filter((e) => e.from === sel.id && drawn.nodes.has(e.to))} side="out" name={name} onPick={setSelected} />
                </>
              )}
              {mode === "impact" && affected && (
                <div className="mt-3 text-xs">
                  <div className="font-semibold uppercase tracking-wide text-slate-500">How it is reached</div>
                  <ol className="mt-1 space-y-0.5">
                    {affected.path.map((s, i) => (
                      <li key={i}>
                        <span className="text-slate-900">{s.provider}</span>{" "}
                        <span style={{ color: LAYER_STYLE[s.layer] ?? "#64748b" }}>{s.relation} ({s.layer})</span> →{" "}
                        <span className="text-slate-900">{s.dependent}</span>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

function Hint({ children }: { children: React.ReactNode }) {
  return <p className="absolute inset-x-0 top-16 z-10 mx-auto w-fit rounded bg-white/90 px-3 py-2 text-sm text-slate-500 shadow-sm">{children}</p>;
}

function Btn({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return <button type="button" onClick={onClick} className="rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50">{children}</button>;
}

function LayerLegend({ edges }: { edges: GEdge[] }) {
  const used = [...new Set(edges.map((e) => e.via).filter((v): v is string => !!v && !!LAYER_STYLE[v]))];
  if (!used.length) return <span>Paths are coloured by how the failure travels.</span>;
  return (
    <span className="flex flex-wrap gap-x-3 gap-y-1">
      {used.map((l) => (
        <span key={l} className="flex items-center gap-1"><span className="inline-block h-0.5 w-5" style={{ background: LAYER_STYLE[l] }} /> {l}</span>
      ))}
    </span>
  );
}
