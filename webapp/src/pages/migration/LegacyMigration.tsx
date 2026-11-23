/** §12: ARGUS's own inferred records become Positions, Equipment and
 * Installations. The plan changes nothing; owners read the report and may
 * override an outcome; applying checks itself item by item; a rollback is
 * possible until the plan is finalized or the domain cuts over. */
import { ask, askText } from "../../lib/dialogs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ledgerApi, legacyMigrationApi, type SerialLineProposal } from "../../api/client";
import type { MigrationAction, MigrationOutcome, MigrationRow } from "../../api/ledgerTypes";
import { errorText } from "../../components/hub/LedgerPanels";
import { Card, Empty } from "../../components/hub/ui";

const OUTCOME: Record<MigrationOutcome, { text: string; tone: string }> = {
  "M-BLOCK": { text: "blocked", tone: "bg-red-50 text-red-700" },
  "M-FUNC": { text: "functional", tone: "bg-slate-100 text-slate-700" },
  "M-POS": { text: "position", tone: "bg-sky-50 text-sky-800" },
  "M-PHYS": { text: "position + equipment", tone: "bg-emerald-50 text-emerald-800" },
  "M-MIXED": { text: "mixed — review", tone: "bg-amber-50 text-amber-800" },
  "M-RETIRE": { text: "retire", tone: "bg-slate-100 text-slate-500" },
  "M-EDGE": { text: "edge rewritten", tone: "bg-indigo-50 text-indigo-700" },
  "M-EDGE-HOLD": { text: "edge — a person decides", tone: "bg-amber-50 text-amber-800" },
};
const CHOICES: MigrationOutcome[] = ["M-POS", "M-PHYS", "M-MIXED", "M-RETIRE", "M-BLOCK"];

function planned(a: MigrationAction): string {
  switch (a.do) {
    case "retype":
      return `position ${a.key}`;
    case "equipment":
      return a.match ? "equipment: the inventory's record" : `equipment (${a.status}) in ${a.workspace}`;
    case "installation":
      return `installation ${a.status}`;
    case "move_labels":
      return `${a.labels?.length} identifier label(s) → equipment`;
    case "move_attachments":
      return `${a.attachments?.length} photo(s) → equipment`;
    case "retire":
      return "retired, not deleted";
    case "edge_to_attribute":
      return `${a.label ?? Object.keys(a.set ?? {}).join(", ")} (edge removed)`;
    case "hold_edge":
      return "kept for now";
    default:
      return "kept as it is";
  }
}

export function LegacyMigrationCard() {
  const queryClient = useQueryClient();
  const plans = useQuery({ queryKey: ["migration-plans"], queryFn: legacyMigrationApi.list, retry: false });
  const gate = useQuery({ queryKey: ["migration-gate"], queryFn: legacyMigrationApi.gate, retry: false });
  const [selected, setSelected] = useState<string | null>(null);
  const current = selected ?? plans.data?.[0]?.id ?? null;
  const refresh = () => {
    for (const key of ["migration-plans", "migration-plan", "migration-gate"]) queryClient.invalidateQueries({ queryKey: [key] });
  };
  const create = useMutation({ mutationFn: () => legacyMigrationApi.plan(), onSuccess: (p) => { setSelected(p.id); refresh(); } });
  if (plans.isError) return null;
  const g = gate.data;
  return (
    <Card
      title="Legacy records"
      action={
        g && (
          <span className={`rounded px-2 py-0.5 text-xs ${g.ok ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-800"}`}>
            {g.ok ? "ready for cutover" : `${g.blocked.length} blocked · ${g.mixed_open.length} to review · ${g.unplanned} unplanned`}
          </span>
        )
      }
    >
      <p className="py-1 text-sm text-slate-600">
        Records the old importer inferred become Positions, Equipment and Installations. Planning changes nothing; a domain
        cannot be frozen for cutover until none is blocked, every mixed one is accepted, and none is left unplanned.
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {(plans.data ?? []).map((p) => (
          <button
            key={p.id}
            onClick={() => setSelected(p.id)}
            className={`rounded border px-2 py-1 font-mono text-xs ${p.id === current ? "border-slate-900" : "border-slate-200"}`}
          >
            {p.id.slice(0, 14)}… · {p.status}
          </button>
        ))}
        <button onClick={() => create.mutate()} className="rounded-md bg-slate-900 px-3 py-1 text-xs font-medium text-white">
          Plan the migration
        </button>
      </div>
      {create.isError && <p className="mt-2 text-sm text-red-600">{errorText(create.error)}</p>}
      {current ? <PlanDetail id={current} onChange={refresh} /> : <Empty>No plan yet.</Empty>}
      <GoldenIncidents />
    </Card>
  );
}

/** I-MIG-7: past incidents with the causes the teams know. The root-cause
 * walk must keep finding them, or more precisely resolved ones. */
function GoldenIncidents() {
  const queryClient = useQueryClient();
  const list = useQuery({ queryKey: ["golden"], queryFn: legacyMigrationApi.golden, retry: false });
  const run = useMutation({ mutationFn: legacyMigrationApi.runGolden });
  const [form, setForm] = useState({ name: "", symptoms: "", causes: "" });
  const split = (v: string) => v.split(",").map((x) => x.trim()).filter(Boolean);
  const add = useMutation({
    mutationFn: () => legacyMigrationApi.addGolden({ name: form.name, symptoms: split(form.symptoms), expected_causes: split(form.causes) }),
    onSuccess: () => { setForm({ name: "", symptoms: "", causes: "" }); queryClient.invalidateQueries({ queryKey: ["golden"] }); },
  });
  const results = Object.fromEntries((run.data?.results ?? []).map((r) => [r.incident, r]));
  return (
    <div className="mt-4 border-t border-slate-100 pt-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-900">Golden incidents (I-MIG-7)</h3>
        <button onClick={() => run.mutate()} className="rounded border border-slate-300 px-2 py-0.5 text-xs">
          {run.isPending ? "Walking…" : "Run the walk"}
        </button>
      </div>
      <p className="text-xs text-slate-500">
        Past incidents and the causes behind them. Their baseline is taken when a plan is first applied; the deep
        verification fails if a cause is no longer found.
      </p>
      <ul className="mt-1 divide-y divide-slate-100 text-sm">
        {(list.data ?? []).map((g) => {
          const r = results[g.id];
          return (
            <li key={g.id} className="flex items-center gap-2 py-1">
              <span className="flex-1 text-slate-800">{g.name}</span>
              <span className="text-xs text-slate-500">{g.symptoms.length} symptom(s) · {g.expected_causes.length} cause(s)</span>
              {r && (
                <span className={`text-xs ${r.found === r.expected ? "text-emerald-700" : "text-red-600"}`}>
                  {r.found} of {r.expected} found
                </span>
              )}
            </li>
          );
        })}
        {list.data?.length === 0 && <li className="py-1 text-xs text-slate-500">None recorded for this workspace.</li>}
      </ul>
      <div className="mt-2 flex flex-wrap gap-1 text-xs">
        <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Incident (name, date)" className="rounded border border-slate-300 px-2 py-1" />
        <input value={form.symptoms} onChange={(e) => setForm({ ...form, symptoms: e.target.value })} placeholder="Symptoms (keys, comma-separated)" className="flex-1 rounded border border-slate-300 px-2 py-1" />
        <input value={form.causes} onChange={(e) => setForm({ ...form, causes: e.target.value })} placeholder="Known causes (keys)" className="flex-1 rounded border border-slate-300 px-2 py-1" />
        <button disabled={!form.name || !form.symptoms || !form.causes} onClick={() => add.mutate()} className="rounded bg-slate-900 px-2 py-1 font-medium text-white disabled:opacity-40">
          Record
        </button>
      </div>
      {(add.isError || run.isError) && <p className="mt-1 text-xs text-red-600">{errorText(add.error ?? run.error)}</p>}
    </div>
  );
}

function PlanDetail({ id, onChange }: { id: string; onChange: () => void }) {
  const plan = useQuery({ queryKey: ["migration-plan", id], queryFn: () => legacyMigrationApi.get(id) });
  const [filter, setFilter] = useState<string>("");
  const act = (fn: (id: string) => Promise<unknown>) => ({ mutationFn: () => fn(id), onSuccess: onChange });
  const apply = useMutation(act(legacyMigrationApi.apply));
  const rollback = useMutation(act(legacyMigrationApi.rollback));
  const finalize = useMutation({
    mutationFn: (waiver?: string) => legacyMigrationApi.finalize(id, waiver),
    onSuccess: onChange,
  });
  const verify = useMutation(act(legacyMigrationApi.verify));
  const override = useMutation({
    mutationFn: (v: { item: number; outcome: string; reason: string }) => legacyMigrationApi.override(id, v.item, v.outcome, v.reason),
    onSuccess: onChange,
  });
  const download = async () => {
    const url = await legacyMigrationApi.reportUrl(id);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${id}.csv`;
    a.click();
  };
  if (!plan.data) return null;
  const p = plan.data;
  const rows = (p.rows ?? []).filter((r) => !filter || r.outcome === filter || r.status === filter);
  const open = p.status !== "finalized" && p.status !== "rolled_back";
  const error = [apply, rollback, finalize, override, verify].find((m) => m.isError)?.error;
  const deep = p.invariants?.deep_verification;
  return (
    <div className="mt-3 space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {Object.entries(p.outcomes).map(([o, n]) => (
          <button key={o} onClick={() => setFilter(filter === o ? "" : o)}
                  className={`rounded px-2 py-0.5 ${OUTCOME[o as MigrationOutcome]?.tone} ${filter === o ? "ring-1 ring-slate-900" : ""}`}>
            {o} {n}
          </button>
        ))}
        <span className="text-slate-400">·</span>
        {Object.entries(p.statuses).map(([s, n]) => (
          <button key={s} onClick={() => setFilter(filter === s ? "" : s)} className={`text-slate-600 ${filter === s ? "underline" : ""}`}>
            {s} {n}
          </button>
        ))}
        <span className="ml-auto flex gap-2">
          <button onClick={download} className="rounded border border-slate-300 px-2 py-1">Report (CSV)</button>
          {open && (
            <button onClick={() => apply.mutate()} disabled={apply.isPending} className="rounded bg-slate-900 px-2 py-1 font-medium text-white">
              {apply.isPending ? "Applying…" : "Apply"}
            </button>
          )}
          {open && p.applied_at && (
            <button onClick={async () => await ask("Undo every applied item of this plan?") && rollback.mutate()}
                    className="rounded border border-red-200 px-2 py-1 text-red-700">
              Roll back
            </button>
          )}
          {open && p.applied_at && (
            <button onClick={() => verify.mutate()} disabled={verify.isPending} className="rounded border border-slate-300 px-2 py-1"
                    title="Data invariants (I-MIG-4); registry report before and after (I-MIG-5); rebuild from the ledger and compare (I-MIG-6)">
              {verify.isPending ? "Verifying…" : "Deep verify"}
            </button>
          )}
          {p.status === "verified" && deep?.ok && (
            <button
              onClick={async () => {
                if (!await ask("After finalizing, the plan can no longer be rolled back.")) return;
                if (deep?.["I-MIG-7"]?.ok === null) {
                  const waiver = await askText("No golden incidents were checked (I-MIG-7). Why can the plan be finalized without them?");
                  if (waiver) finalize.mutate(waiver);
                } else finalize.mutate(undefined);
              }}
                    className="rounded border border-slate-300 px-2 py-1">
              Finalize
            </button>
          )}
        </span>
      </div>
      {p.invariants && (
        <p className="text-xs text-slate-600">
          {Object.entries(p.invariants.checks).map(([k, ok]) => (
            <span key={k} className={`mr-3 ${ok ? "text-emerald-700" : "text-red-600"}`}>{ok ? "✓" : "✗"} {k}</span>
          ))}
          {deep ? (
            <>
              {deep["I-MIG-4"] && (
                <span className={`mr-3 ${deep["I-MIG-4"].ok ? "text-emerald-700" : "text-red-600"}`}>
                  {deep["I-MIG-4"].ok ? "✓ I-MIG-4 (data invariants)" : `✗ I-MIG-4 (${deep["I-MIG-4"].failing.join(", ")})`}
                </span>
              )}
              <span className={`mr-3 ${deep["I-MIG-5"].ok ? "text-emerald-700" : "text-red-600"}`}
                    title={deep["I-MIG-5"].grew && Object.keys(deep["I-MIG-5"].grew).length ? `grew: ${Object.keys(deep["I-MIG-5"].grew).join(", ")}` : undefined}>
                {deep["I-MIG-5"].ok ? "✓" : "✗"} I-MIG-5 (registry {deep["I-MIG-5"].before ?? "?"} → {deep["I-MIG-5"].after ?? "?"})
              </span>
              <span className={`mr-3 ${deep["I-MIG-6"].ok ? "text-emerald-700" : "text-red-600"}`}>
                {deep["I-MIG-6"].ok ? "✓" : "✗"} I-MIG-6 (rebuild: {deep["I-MIG-6"].differences.length} of {deep["I-MIG-6"].records} differ)
              </span>
              {deep["I-MIG-7"] && (
                <span className={`mr-3 ${deep["I-MIG-7"].ok ? "text-emerald-700" : deep["I-MIG-7"].ok === null ? "text-amber-700" : "text-red-600"}`}
                      title={deep["I-MIG-7"].reason ?? (deep["I-MIG-7"].lost ?? []).map((l) => `${l.incident}: lost ${l.cause}`).join("; ")}>
                  {deep["I-MIG-7"].ok ? "✓" : deep["I-MIG-7"].ok === null ? "–" : "✗"} I-MIG-7 (golden incidents
                  {deep["I-MIG-7"].ok === null ? ": none recorded" : `: ${deep["I-MIG-7"].before} → ${deep["I-MIG-7"].after} causes found`})
                </span>
              )}
            </>
          ) : (
            <span className="mr-3 text-slate-500">I-MIG-4, I-MIG-5, I-MIG-6: deep verification not run</span>
          )}
          {p.invariants.not_automated.length > 0 && (
            <span className="text-slate-400">checked by people: {p.invariants.not_automated.map((x) => x.split(" ")[0]).join(", ")}</span>
          )}
        </p>
      )}
      {error && <p className="text-sm text-red-600">{errorText(error)}</p>}
      <div className="max-h-[32rem] overflow-y-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-white text-left text-xs text-slate-400">
            <tr>
              <th className="py-1 font-normal">Record</th>
              <th className="font-normal">Outcome</th>
              <th className="font-normal">Becomes</th>
              <th className="font-normal">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 align-top">
            {rows.map((r) => (
              <Row key={r.item} r={r} open={open} onOverride={(outcome, reason) => override.mutate({ item: r.item, outcome, reason })} />
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <Empty>No inferred record is waiting for migration.</Empty>}
      </div>
    </div>
  );
}

function Row({ r, open, onOverride }: { r: MigrationRow; open: boolean; onOverride: (outcome: string, reason: string) => void }) {
  const o = OUTCOME[r.outcome];
  return (
    <tr>
      <td className="py-1.5 pr-3">
        <Link to={`/assets/${r.outcome.startsWith("M-EDGE") ? String(r.evidence.from) : r.legacy_uid}`}
              className="font-mono text-xs text-slate-800 hover:underline">{r.legacy_key}</Link>
        <span className="block text-xs text-slate-400">{r.legacy_type}</span>
        {r.warnings.map((w) => (
          <span key={w} className="block text-[11px] text-amber-700">{w}</span>
        ))}
      </td>
      <td className="pr-3">
        <span className={`rounded px-1.5 py-0.5 text-xs ${o.tone}`} title={`confidence ${r.confidence}`}>{o.text}</span>
        {r.override && <span className="block text-[11px] text-slate-500" title={r.override.reason}>overridden by {r.override.by}</span>}
        {open && r.status !== "applied" && r.outcome !== "M-FUNC" && !r.outcome.startsWith("M-EDGE") && (
          <select
            value=""
            onChange={async (e) => {
              const reason = e.target.value && await askText(`Why ${e.target.value}?`);
              if (reason) onOverride(e.target.value, reason);
            }}
            className="mt-1 block rounded border border-slate-200 text-[11px]"
          >
            <option value="">Override…</option>
            {CHOICES.filter((c) => c !== r.outcome).map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        )}
      </td>
      <td className="pr-3 text-xs text-slate-600">
        {r.actions.map((a, i) => (
          <span key={i} className="block">{planned(a)}</span>
        ))}
      </td>
      <td className="text-xs">
        {r.outcome === "M-EDGE-HOLD" && r.status === "applied" ? (
          <span className="text-amber-700">held for a person</span>
        ) : (
          <span className={r.status === "applied" ? "text-emerald-700" : r.status === "failed" || r.status === "stale" ? "text-red-600" : "text-slate-500"}>
            {r.status}
          </span>
        )}
        {r.reason && <span className="block text-[11px] text-slate-500">{r.reason}</span>}
      </td>
    </tr>
  );
}


/** §13 S5: once a workspace's legacy records are migrated, its record facts
 * and relations can be made to change only through the fact ledger. The
 * database refuses anything else. */
export function LedgerOnlyCard() {
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: ["ledger-only"], queryFn: ledgerApi.ledgerOnly, retry: false });
  const set = useMutation({
    mutationFn: (v: { enabled: boolean; reason: string }) => ledgerApi.setLedgerOnly(v.enabled, v.reason),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["ledger-only"] }),
  });
  if (!status.data) return null;
  const s = status.data;
  const toggle = async (enabled: boolean) => {
    const reason = await askText(enabled ? "Why switch this workspace to ledger-only?" : "Why switch ledger-only off?");
    if (reason) set.mutate({ enabled, reason });
  };
  return (
    <Card
      title="Ledger-only writes (§13 S5)"
      action={
        <span className={`rounded px-2 py-0.5 text-xs ${s.enabled ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>
          {s.enabled ? "on" : "off"}
        </span>
      }
    >
      <p className="py-1 text-sm text-slate-600">
        {s.enabled
          ? "Record attributes, names, types, status and relations change only through the fact ledger: every change is attributed to its author, and the database refuses anything written around it. Deleting a record retires it."
          : "When on, record facts and relations change only through the fact ledger, and the database refuses anything written around it."}
      </p>
      {!s.enabled && !s.legacy.ok && (
        <p className="text-xs text-amber-700">
          Migrate the legacy records first: {s.legacy.blocked.length} blocked, {s.legacy.mixed_open.length} to review,{" "}
          {s.legacy.unplanned} unplanned.
        </p>
      )}
      <button
        onClick={() => toggle(!s.enabled)}
        disabled={!s.enabled && !s.legacy.ok}
        className="mt-2 rounded-md border border-slate-300 px-3 py-1 text-xs disabled:opacity-40"
      >
        {s.enabled ? "Switch off" : "Switch on"}
      </button>
      {set.isError && <p className="mt-1 text-xs text-red-600">{errorText(set.error)}</p>}
    </Card>
  );
}


/** §13 S7: the relation registry warns, or, once every violation is fixed
 * or accepted, enforces: a new edge that breaks it is refused. */
export function RegistryCard() {
  const queryClient = useQueryClient();
  const rep = useQuery({ queryKey: ["registry"], queryFn: ledgerApi.registry, retry: false });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["registry"] });
  const accept = useMutation({ mutationFn: (v: { id: string; reason: string }) => ledgerApi.acceptViolation(v.id, v.reason), onSuccess: refresh });
  const mode = useMutation({ mutationFn: (v: { mode: "warn" | "enforce"; reason: string }) => ledgerApi.setRegistryMode(v.mode, v.reason), onSuccess: refresh });
  if (!rep.data) return null;
  const r = rep.data;
  const enforce = r.mode === "enforce";
  const open = r.violations.filter((v) => !v.explained_by);
  return (
    <Card
      title="Relation registry (§6, §13 S7)"
      action={<span className={`rounded px-2 py-0.5 text-xs ${enforce ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>{String(r.mode)}</span>}
    >
      <p className="py-1 text-sm text-slate-600">
        {r.total} violation(s), {r.unexplained} neither fixed nor accepted.{" "}
        {enforce ? "Enforced: a new edge that breaks the registry is refused." : "Warn mode: violations are reported, not refused."}
      </p>
      <ul className="max-h-72 divide-y divide-slate-100 overflow-y-auto text-sm">
        {open.slice(0, 50).map((v) => (
          <li key={v.id} className="flex items-center gap-2 py-1">
            <span className="rounded bg-slate-100 px-1.5 text-[11px] text-slate-600">{v.rule}</span>
            <span className="flex-1 text-slate-700">{v.message}</span>
            <button onClick={async () => { const why = await askText("Why is this edge right although the registry would not allow it?"); if (why) accept.mutate({ id: v.id, reason: why }); }}
                    className="text-xs text-indigo-700 hover:underline">Accept as exception</button>
          </li>
        ))}
      </ul>
      <button
        onClick={async () => { const why = await askText(enforce ? "Why go back to warn mode?" : "Why enforce the registry here?"); if (why) mode.mutate({ mode: enforce ? "warn" : "enforce", reason: why }); }}
        disabled={!enforce && r.unexplained > 0}
        className="mt-2 rounded-md border border-slate-300 px-3 py-1 text-xs disabled:opacity-40"
      >
        {enforce ? "Back to warn mode" : "Enforce"}
      </button>
      {(accept.isError || mode.isError) && <p className="mt-1 text-xs text-red-600">{errorText(accept.error ?? mode.error)}</p>}
    </Card>
  );
}


/** §9.1, §12.4: the old importer's Serial Lines, one at a time. Each becomes a
 * Bus Segment behind a Communication Path from its IOC to the Access Point;
 * the golden incidents are walked before and after, and a lost cause refuses
 * the conversion unless a person accepts it with a reason. */
export function SerialLinesCard() {
  const queryClient = useQueryClient();
  const q = useQuery({ queryKey: ["serial-lines"], queryFn: ledgerApi.serialLines, retry: false });
  const [done, setDone] = useState<string | null>(null);
  const convert = useMutation({
    mutationFn: (v: { uid: string; key: string; reason: string; access_point_uid?: string; accept_golden_loss?: string }) =>
      ledgerApi.convertSerialLine(v.uid, { reason: v.reason, access_point_uid: v.access_point_uid, accept_golden_loss: v.accept_golden_loss }),
    onSuccess: (r, v) => {
      setDone(`${v.key}: ${r.paths.length} path(s), ${r.removed.length} old edge(s) removed` +
              (r.golden.ok === null ? ", no golden incidents to check" : r.golden.ok ? ", golden incidents unchanged" : ", a golden cause accepted as lost"));
      queryClient.invalidateQueries();              // types, counts and the registry all change
    },
  });
  if (!q.data) return null;
  const lines = q.data.lines;

  async function run(p: SerialLineProposal, ap?: string) {
    const reason = await askText(`Why convert ${p.line.key}?`);
    if (!reason) return;
    convert.mutate({ uid: p.line.uid, key: p.line.key, reason, access_point_uid: ap }, {
      onError: async (e) => {
        const text = errorText(e);
        if (!text.includes("lose a cause")) return;
        const accept = await askText(`${text}\n\nConvert anyway? Say why the walk may lose it.`);
        if (accept) convert.mutate({ uid: p.line.uid, key: p.line.key, reason, access_point_uid: ap, accept_golden_loss: accept });
      },
    });
  }

  return (
    <Card title="Serial lines">
      <p className="py-1 text-sm text-slate-600">
        {lines.length === 0
          ? "No Serial Line is left: every one is a Bus Segment behind a Communication Path."
          : `${lines.length} line(s) from the old importer. Converting one retypes it in place as a Bus Segment, draws a path from each IOC to the Access Point, and removes its old edges.`}
      </p>
      <ul className="divide-y divide-slate-100 text-sm">
        {lines.map((p) => <SerialLineRow key={p.line.uid} p={p} busy={convert.isPending} onConvert={(ap) => run(p, ap)} />)}
      </ul>
      {done && <p className="mt-1 text-xs text-emerald-700">{done}</p>}
      {convert.isError && <p className="mt-1 text-xs text-red-600">{errorText(convert.error)}</p>}
    </Card>
  );
}

function SerialLineRow({ p, busy, onConvert }: { p: SerialLineProposal; busy: boolean; onConvert: (ap?: string) => void }) {
  const [ap, setAp] = useState(p.access_point?.uid ?? "");
  const blocking = p.questions.filter((x) => !x.includes("Access Points") || !ap);
  return (
    <li className="py-2">
      <div className="flex items-center gap-2">
        <Link to={`/assets/${p.line.uid}`} className="font-medium text-indigo-700 hover:underline">{p.line.key}</Link>
        {p.required_port && <span className="rounded bg-slate-100 px-1.5 text-[11px] text-slate-600">port {p.required_port.tcp_port} (advisory)</span>}
        <span className="flex-1" />
        {p.access_points.length > 1 && (
          <select value={ap} onChange={(e) => setAp(e.target.value)} className="rounded border border-slate-300 px-1 py-0.5 text-xs">
            <option value="">Access Point…</option>
            {p.access_points.map((a) => <option key={a.uid} value={a.uid}>{a.key}</option>)}
          </select>
        )}
        <button onClick={() => onConvert(ap || undefined)} disabled={busy || blocking.length > 0}
                className="rounded-md border border-slate-300 px-3 py-1 text-xs disabled:opacity-40">Convert</button>
      </div>
      <p className="mt-0.5 text-xs text-slate-600">
        enters at {p.access_point?.key ?? (p.access_points.length ? "one of " + p.access_points.map((a) => a.key).join(", ") : "—")}
        {p.converter && <> · implemented by {p.converter.key}{p.implements_access_point ? " (already set)" : ""}</>}
        {" · "}{p.paths.map((g) => `${g.ioc.key} → ${g.devices.length} device(s)`).join("; ") || "no path"}
      </p>
      {p.questions.map((x) => <p key={x} className="text-xs text-amber-700">{x}</p>)}
    </li>
  );
}
