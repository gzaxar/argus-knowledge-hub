/** Moving a domain from Jira and Insight to ARGUS, stage by stage: import,
 * shadow validation, freeze at the watermark, reconciliation, and the signed
 * exit that makes ARGUS the system of record for it. Nothing here writes to
 * Jira or Insight. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, auditApi, domainsApi, ledgerApi, retirementApi } from "../../api/client";
import type { DomainDetail, DomainView, ReconciliationDifference } from "../../api/ledgerTypes";
import { errorText } from "../../components/hub/LedgerPanels";
import { Card, Empty } from "../../components/hub/ui";
import { LedgerOnlyCard, LegacyMigrationCard, RegistryCard, SerialLinesCard } from "./LegacyMigration";

const STAGES = ["T0", "T1", "T2", "T3", "T4", "T5"] as const;
const STAGE_HELP: Record<string, string> = {
  T0: "Prepare: stewards, mappings and readiness items.",
  T1: "Import and reconcile: ARGUS holds a read-only mirror; stewards work the queues.",
  T2: "Shadow validation: incremental imports and a reconciliation report per run.",
  T3: "Cutover: the source is read-only, the streams are frozen at the watermark W.",
  T4: "Archive: the source stays readable; exports verified; redirects active.",
  T5: "Retire Jira: every domain past T4.",
};
const ATTESTATIONS: Record<string, string> = {
  jira_write_refused: "A write attempt against the Jira or Insight scope fails",
  smoke_tests: "Create, edit, search, link and a ticket workflow pass in ARGUS",
  export_verified: "The immutable export is taken and its checksums verified",
};

export function MigrationPage() {
  const domains = useQuery({ queryKey: ["domains"], queryFn: domainsApi.list });
  const [selected, setSelected] = useState<string | null>(null);
  const current = selected ?? domains.data?.[0]?.id ?? null;
  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Migration from Jira</h1>
        <p className="mt-0.5 max-w-3xl text-sm text-slate-500">
          For teams leaving Jira and Insight for ARGUS. A <i>domain</i> is a part of what Jira holds (a project, an
          object schema) that moves as one: it is imported, compared with Jira while both run, frozen in Jira, and
          finally signed over, after which ARGUS is where it is kept and changed. Until a domain's exit is signed,
          Jira stays authoritative and ARGUS holds it read-only; after it, there is no way back to Jira. A workspace
          that never used Jira has nothing to do here.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[18rem_1fr]">
        <div className="space-y-3">
          <Card title="Domains">
            {domains.data && domains.data.length === 0 ? (
              <Empty>No domain yet.</Empty>
            ) : (
              <ul className="divide-y divide-slate-100">
                {(domains.data ?? []).map((d: DomainView) => (
                  <li key={d.id}>
                    <button
                      onClick={() => setSelected(d.id)}
                      className={`flex w-full items-center justify-between gap-2 py-2 text-left text-sm ${
                        d.id === current ? "font-semibold text-slate-900" : "text-slate-700"
                      }`}
                    >
                      <span className="min-w-0 truncate">{d.name}</span>
                      <StageBadge d={d} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <NewDomainForm onCreated={setSelected} />
        </div>
        {current ? <DomainPanel id={current} /> : <Empty>Create a domain to start.</Empty>}
      </div>
      <LegacyMigrationCard />
      <LedgerOnlyCard />
      <RegistryCard />
      <SerialLinesCard />
      <AuditIntegrity />
      <RetirementCard />
    </div>
  );
}

/** §19 item 14: Jira is retired once, when every condition holds. Administrators only. */
function RetirementCard() {
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: ["retirement"], queryFn: retirementApi.status, retry: false });
  const [attested, setAttested] = useState<Record<string, boolean>>({});
  const [retention, setRetention] = useState({ reference: "", jira_archive_until: "" });
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["retirement"] });
    queryClient.invalidateQueries({ queryKey: ["domains"] });
    queryClient.invalidateQueries({ queryKey: ["domain"] });
  };
  const record = useMutation({ mutationFn: () => retirementApi.recordRetention(retention), onSuccess: refresh });
  const sign = useMutation({ mutationFn: () => retirementApi.sign(attested), onSuccess: refresh });
  if (status.error instanceof ApiError && status.error.status === 403) return null;
  if (!status.data) return null;
  const s = status.data;
  const observed = s.conditions.filter((c) => !c.attested);
  const openCount = observed.filter((c) => !c.ok).length + Object.keys(s.attestations).filter((k) => !attested[k]).length;
  const retentionOpen = observed.some((c) => c.id === "retention" && !c.ok);
  return (
    <Card
      title="Jira retirement (§19 item 14)"
      action={
        s.retired ? (
          <span className="rounded bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">retired</span>
        ) : (
          <span className="text-xs text-slate-400">{openCount} open</span>
        )
      }
    >
      {s.retired ? (
        <p className="py-1 text-sm text-slate-700">
          Jira was retired on {new Date(s.retired_at!).toLocaleString()} by {s.signed_by}. Its links resolve through the lookup.
        </p>
      ) : (
        <>
          <ul className="space-y-1 py-1 text-sm">
            {observed.map((c) => (
              <li key={c.id} className="flex gap-2">
                <span className={c.ok ? "text-emerald-600" : "text-red-600"}>{c.ok ? "✓" : "✗"}</span>
                <span className="text-slate-700">{c.text}</span>
                <span className="ml-auto text-[11px] text-slate-400">§19 {c.item}</span>
              </li>
            ))}
            {Object.entries(s.attestations).map(([k, text]) => (
              <li key={k}>
                <label className="flex gap-2">
                  <input type="checkbox" checked={!!attested[k]} onChange={(e) => setAttested({ ...attested, [k]: e.target.checked })} />
                  <span className="text-slate-700">{text}</span>
                </label>
              </li>
            ))}
          </ul>
          {retentionOpen && (
            <div className="mt-2 flex flex-wrap items-center gap-2 rounded border border-slate-200 bg-slate-50 p-2 text-xs">
              <span className="font-medium text-slate-700">Retention decision (U1)</span>
              <input value={retention.reference} onChange={(e) => setRetention({ ...retention, reference: e.target.value })}
                     placeholder="Records policy or legal basis" className="flex-1 rounded border border-slate-300 px-2 py-1" />
              <label className="flex items-center gap-1 text-slate-600">
                Jira archive kept until
                <input type="date" value={retention.jira_archive_until}
                       onChange={(e) => setRetention({ ...retention, jira_archive_until: e.target.value })}
                       className="rounded border border-slate-300 px-2 py-1" />
              </label>
              <button disabled={!retention.reference || !retention.jira_archive_until} onClick={() => record.mutate()}
                      className="rounded border border-slate-300 bg-white px-2 py-1 disabled:opacity-40">
                Record
              </button>
            </div>
          )}
          <button disabled={openCount > 0 || sign.isPending} onClick={() => sign.mutate()}
                  className="mt-3 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40">
            Sign the retirement of Jira
          </button>
          {(record.isError || sign.isError) && <p className="mt-2 text-sm text-red-600">{errorText(record.error ?? sign.error)}</p>}
        </>
      )}
    </Card>
  );
}

/** The append-only log's daily digest chain: copy each digest out of ARGUS;
 * verification recomputes the chain from the events. */
function AuditIntegrity() {
  const queryClient = useQueryClient();
  const digests = useQuery({ queryKey: ["audit-digests"], queryFn: auditApi.digests });
  const verify = useMutation({ mutationFn: auditApi.verify });
  const seal = useMutation({
    mutationFn: auditApi.seal,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["audit-digests"] }),
  });
  return (
    <Card
      title="Audit log integrity"
      action={
        <span className="flex gap-2">
          <button onClick={() => seal.mutate()} className="rounded border border-slate-300 px-2 py-1 text-xs">
            Seal yesterday
          </button>
          <button onClick={() => verify.mutate()} className="rounded bg-slate-900 px-2 py-1 text-xs text-white">
            Verify the chain
          </button>
        </span>
      }
    >
      {verify.data && (
        <p className={`py-1 text-sm ${verify.data.ok ? "text-emerald-700" : "text-red-700"}`}>
          {verify.data.ok
            ? `Intact: ${verify.data.days} sealed day(s), head ${verify.data.head?.slice(0, 16) ?? "—"}…`
            : `Broken at ${verify.data.day}: ${verify.data.reason}`}
        </p>
      )}
      {(seal.error || verify.error) && <p className="text-sm text-red-600">{errorText(seal.error ?? verify.error)}</p>}
      {(digests.data ?? []).length === 0 ? (
        <Empty>No day sealed yet. Run `python -m app.ledger audit-digest` daily and keep its output outside ARGUS.</Empty>
      ) : (
        <ul className="divide-y divide-slate-50 font-mono text-xs">
          {digests.data!.slice(0, 7).map((d) => (
            <li key={d.day} className="flex justify-between gap-3 py-1">
              <span>{d.day}</span>
              <span className="truncate text-slate-500">{d.digest}</span>
              <span className="shrink-0 text-slate-400">
                {Object.values(d.counts).reduce((a, b) => a + b, 0)} events
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function StageBadge({ d }: { d: DomainView }) {
  const tone = d.authoritative
    ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
    : d.stage === "T3"
      ? "bg-amber-50 text-amber-800 ring-amber-200"
      : "bg-slate-100 text-slate-600 ring-slate-200";
  return (
    <span className={`shrink-0 rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset ${tone}`}>
      {d.authoritative ? `${d.stage} · in ARGUS` : d.stage}
    </span>
  );
}

function NewDomainForm({ onCreated }: { onCreated: (id: string) => void }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [resource, setResource] = useState("objects");
  const [streams, setStreams] = useState<string[]>([]);
  const [archive, setArchive] = useState("");
  const available = useQuery({ queryKey: ["ledger-streams"], queryFn: ledgerApi.streams, enabled: open });
  const create = useMutation({
    mutationFn: () =>
      domainsApi.create({ id, name, resource, stream_ids: streams, pilot: false, archive_url: archive || undefined }),
    onSuccess: (d) => {
      queryClient.invalidateQueries({ queryKey: ["domains"] });
      setOpen(false);
      onCreated(d.id);
    },
  });
  if (!open)
    return (
      <button onClick={() => setOpen(true)} className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium">
        New domain…
      </button>
    );
  const sources = (available.data ?? []).filter((s) => !["person", "resolver", "system"].includes(s.kind));
  return (
    <Card title="New domain">
      <div className="space-y-2 py-1 text-xs text-slate-600">
        <label className="block">
          Id
          <input value={id} onChange={(e) => setId(e.target.value)} className="mt-1 block w-full rounded border border-slate-300 px-2 py-1 text-sm" />
        </label>
        <label className="block">
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} className="mt-1 block w-full rounded border border-slate-300 px-2 py-1 text-sm" />
        </label>
        <label className="block">
          Scope
          <select value={resource} onChange={(e) => setResource(e.target.value)} className="mt-1 block w-full rounded border border-slate-300 px-2 py-1 text-sm">
            <option value="objects">Equipment and positions</option>
            <option value="tickets">Tickets</option>
            <option value="documents">Documents</option>
          </select>
        </label>
        <fieldset>
          <legend>Source streams</legend>
          {sources.map((s) => (
            <label key={s.id} className="flex items-center gap-2 font-mono text-[11px]">
              <input
                type="checkbox"
                checked={streams.includes(s.id)}
                onChange={(e) => setStreams(e.target.checked ? [...streams, s.id] : streams.filter((x) => x !== s.id))}
              />
              {s.id}
            </label>
          ))}
        </fieldset>
        <label className="block">
          Archive URL (use {"{key}"} for the identifier)
          <input value={archive} onChange={(e) => setArchive(e.target.value)} className="mt-1 block w-full rounded border border-slate-300 px-2 py-1 text-sm" />
        </label>
        {create.isError && <p className="text-red-600">{errorText(create.error)}</p>}
        <button
          disabled={!id || !name || create.isPending}
          onClick={() => create.mutate()}
          className="rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
        >
          Create
        </button>
      </div>
    </Card>
  );
}

function DomainPanel({ id }: { id: string }) {
  const queryClient = useQueryClient();
  const detail = useQuery({ queryKey: ["domain", id], queryFn: () => domainsApi.get(id) });
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["domain", id] });
    queryClient.invalidateQueries({ queryKey: ["domains"] });
  };
  const [attested, setAttested] = useState<Record<string, boolean>>({});
  const stage = useMutation({ mutationFn: (s: string) => domainsApi.stage(id, s), onSuccess: refresh });
  const exit = useMutation({ mutationFn: () => domainsApi.exit(id, attested), onSuccess: refresh });
  if (!detail.data) return <Empty>Loading…</Empty>;
  const d: DomainDetail = detail.data;
  const index = STAGES.indexOf(d.stage);
  const next = STAGES[index + 1];
  const error = [stage, exit].find((m) => m.isError)?.error;
  return (
    <div className="space-y-4">
      <Card title={d.name} action={<StageBadge d={d} />}>
        <ol className="grid grid-cols-6 gap-1 py-2">
          {STAGES.map((s, i) => (
            <li
              key={s}
              title={STAGE_HELP[s]}
              className={`rounded px-2 py-1.5 text-center text-[11px] ${
                i < index || (s === "T3" && d.authoritative)
                  ? "bg-emerald-50 text-emerald-800"
                  : i === index
                    ? "bg-slate-900 text-white"
                    : "bg-slate-50 text-slate-400"
              }`}
            >
              <span className="block font-semibold">{s}</span>
              {d.stages[s]}
            </li>
          ))}
        </ol>
        <p className="text-xs text-slate-600">{STAGE_HELP[d.stage]}</p>
        <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-600">
          {d.streams.map((s) => (
            <span key={s.id} className="rounded border border-slate-200 px-2 py-0.5 font-mono">
              {s.id} {s.frozen_at ? "· frozen" : ""}
            </span>
          ))}
          {d.watermark && <span className="font-mono">W = {JSON.stringify(d.watermark)}</span>}
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {next === "T5" && (
            <span className="text-xs text-slate-500">T5 is reached by signing the Jira retirement below, for every domain at once.</span>
          )}
          {next && next !== "T3" && next !== "T5" && (d.stage !== "T3" || d.authoritative) && (
            <button onClick={() => stage.mutate(next)} className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium">
              Move to {next} {d.stages[next]}
            </button>
          )}
          {d.stage === "T3" && !d.authoritative && (
            <button onClick={() => stage.mutate("T2")} className="rounded-md border border-red-200 px-3 py-1.5 text-xs text-red-700">
              Abort the cutover (back to T2)
            </button>
          )}
        </div>
        {error && <p className="mt-2 text-sm text-red-600">{errorText(error)}</p>}
      </Card>

      {(d.stage === "T1" || d.stage === "T2") && <FreezeForm d={d} onDone={refresh} />}
      {d.stage !== "T0" && <ReconcileCard d={d} onDone={refresh} />}

      {d.stage === "T3" && (
        <Card title="Exit criteria (§17.5)">
          <ul className="space-y-1.5 py-1">
            {d.exit_criteria.map((c) => (
              <li key={c.id} className="flex items-start gap-2 text-sm">
                {c.attested ? (
                  <input
                    type="checkbox"
                    disabled={d.authoritative}
                    checked={d.authoritative || !!attested[c.id]}
                    onChange={(e) => setAttested({ ...attested, [c.id]: e.target.checked })}
                    className="mt-1"
                  />
                ) : (
                  <span className={c.ok ? "text-emerald-600" : "text-red-600"}>{c.ok ? "✓" : "✗"}</span>
                )}
                <span className={c.ok || attested[c.id] || d.authoritative ? "text-slate-800" : "text-slate-600"}>
                  {c.text}
                  {c.attested && <span className="ml-1 text-[11px] text-slate-400">(attested by the signer)</span>}
                </span>
              </li>
            ))}
          </ul>
          {d.authoritative && d.pilot && <PilotReversion d={d} onDone={refresh} />}
          {!d.authoritative ? (
            <button
              onClick={() => exit.mutate()}
              className="mt-2 rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white"
            >
              Sign the exit — ARGUS becomes the system of record
            </button>
          ) : (
            <p className="mt-2 text-sm text-emerald-700">
              Signed {new Date(d.exited_at!).toLocaleString()}. Editing is open in ARGUS for this domain.
            </p>
          )}
        </Card>
      )}
    </div>
  );
}

function JsonArea({ label, value, onChange, rows = 6 }: { label: string; value: string; onChange: (v: string) => void; rows?: number }) {
  return (
    <label className="block text-xs text-slate-600">
      {label}
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={rows}
        spellCheck={false}
        className="mt-1 block w-full rounded border border-slate-300 px-2 py-1 font-mono text-xs"
      />
    </label>
  );
}

function parse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

/** §17.4: the domain is frozen only when the entry criteria hold, each met
 * or waived by the governance group with a reason. */
function FreezeForm({ d, onDone }: { d: DomainDetail; onDone: () => void }) {
  const [watermark, setWatermark] = useState('{"updated": "", "changelog_id": 0}');
  const [manifest, setManifest] = useState('{"objects": [], "issues": [], "users": []}');
  const [attested, setAttested] = useState<Record<string, boolean>>({});
  const [waivers, setWaivers] = useState<Record<string, string>>({});
  const [stewards, setStewards] = useState({ steward: d.steward ?? "", backup: d.backup_steward ?? "" });
  const cleanWaivers = Object.fromEntries(Object.entries(waivers).filter(([, v]) => v.trim()));
  const freeze = useMutation({
    mutationFn: () => domainsApi.freeze(d.id, parse(watermark), parse(manifest), attested, cleanWaivers),
    onSuccess: onDone,
  });
  const saveStewards = useMutation({ mutationFn: () => domainsApi.setStewards(d.id, stewards.steward, stewards.backup), onSuccess: onDone });
  const valid = parse(watermark) !== undefined && parse(manifest) !== undefined;
  const criteria = d.entry_criteria ?? [];
  const open = criteria.filter((c) => !(c.attested ? attested[c.id] : c.met || (c.waivable && waivers[c.id]?.trim()))).length;
  return (
    <Card title="Entry criteria and freeze (§17.4, T3)" action={<span className="text-xs text-slate-400">{open} open</span>}>
      <ul className="space-y-1.5 py-1 text-sm">
        {criteria.map((c) => (
          <li key={c.id} className="flex flex-wrap items-start gap-2">
            {c.attested ? (
              <input type="checkbox" className="mt-1" checked={!!attested[c.id]} onChange={(e) => setAttested({ ...attested, [c.id]: e.target.checked })} />
            ) : (
              <span className={c.met ? "text-emerald-600" : waivers[c.id]?.trim() ? "text-amber-600" : "text-red-600"}>
                {c.met ? "✓" : waivers[c.id]?.trim() ? "≈" : "✗"}
              </span>
            )}
            <span className="flex-1 text-slate-700">
              {c.text}
              {c.id === "t2" && c.detail && (
                <span className="block text-xs text-slate-500">
                  {String(c.detail.days)} day(s) in T2 · {String(c.detail.clean_runs)} consecutive clean run(s)
                  {c.detail.over_limit ? " · past 8 weeks: the governance group decides" : ""}
                </span>
              )}
              {c.id === "queues_ageing" && c.detail && Number(c.detail.overdue) > 0 && (
                <span className="block text-xs text-slate-500">{String(c.detail.overdue)} item(s) past their target</span>
              )}
              {c.id === "stewards" && (
                <span className="mt-1 flex flex-wrap gap-1 text-xs">
                  <input value={stewards.steward} onChange={(e) => setStewards({ ...stewards, steward: e.target.value })} placeholder="Steward" className="rounded border border-slate-300 px-2 py-0.5" />
                  <input value={stewards.backup} onChange={(e) => setStewards({ ...stewards, backup: e.target.value })} placeholder="Backup" className="rounded border border-slate-300 px-2 py-0.5" />
                  <button onClick={() => saveStewards.mutate()} className="rounded border border-slate-300 px-2 py-0.5">Save</button>
                </span>
              )}
            </span>
            <span className="text-[11px] text-slate-400">§17.4 ({c.criterion})</span>
            {!c.met && !c.attested && c.waivable && (
              <input
                value={waivers[c.id] ?? ""}
                onChange={(e) => setWaivers({ ...waivers, [c.id]: e.target.value })}
                placeholder="Waiver: the governance group's reason"
                className="basis-full rounded border border-slate-200 px-2 py-0.5 text-xs"
              />
            )}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-slate-500">
        Take the freeze only after the source scope is read-only. W and the export manifest's hash are recorded on each
        stream's final revision; the streams then refuse every later revision. Waivers are written into the freeze decision.
      </p>
      <div className="mt-2 grid grid-cols-1 gap-3 md:grid-cols-2">
        <JsonArea label="Watermark W" value={watermark} onChange={setWatermark} rows={3} />
        <JsonArea label="Export manifest" value={manifest} onChange={setManifest} rows={3} />
      </div>
      {(freeze.isError || saveStewards.isError) && (
        <p className="mt-2 text-sm text-red-600">{errorText(freeze.error ?? saveStewards.error)}</p>
      )}
      <button
        disabled={!valid || open > 0 || freeze.isPending}
        onClick={() => freeze.mutate()}
        className="mt-2 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
      >
        Freeze the streams
      </button>
    </Card>
  );
}

function ReconcileCard({ d, onDone }: { d: DomainDetail; onDone: () => void }) {
  const [manifest, setManifest] = useState("");
  const [reason, setReason] = useState<Record<string, string>>({});
  const run = useMutation({ mutationFn: () => domainsApi.reconcile(d.id, parse(manifest)), onSuccess: onDone });
  const explain = useMutation({
    mutationFn: (diff: ReconciliationDifference) => domainsApi.explain(d.id, diff.id, reason[diff.id] ?? ""),
    onSuccess: onDone,
  });
  const report = d.report;
  return (
    <Card
      title="Reconciliation report"
      action={
        report ? (
          <span className={`text-xs font-medium ${report.passed ? "text-emerald-700" : "text-red-700"}`}>
            {report.passed ? "passed" : `${report.unexplained} unexplained difference(s)`}
          </span>
        ) : undefined
      }
    >
      {report ? (
        <>
          <table className="mt-1 w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-slate-400">
                <th className="py-1 font-medium">Record type</th>
                <th className="py-1 font-medium">Source</th>
                <th className="py-1 font-medium">ARGUS</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(report.sections).map(([k, v]) => (
                <tr key={k} className="border-t border-slate-50">
                  <td className="py-1 capitalize">{k}</td>
                  <td className="py-1 tabular-nums">{v.source}</td>
                  <td className={`py-1 tabular-nums ${v.source !== v.argus ? "text-red-700" : ""}`}>{v.argus}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {report.differences.length > 0 && (
            <ul className="mt-3 divide-y divide-slate-100">
              {report.differences.map((x) => (
                <li key={x.id} className="py-2 text-sm">
                  <p>
                    <span className="mr-2 rounded bg-slate-100 px-1.5 text-[11px]">{x.section}</span>
                    <span className="font-mono text-xs">{x.item}</span> — {x.message}
                    {x.sha256 && <span className="ml-1 font-mono text-[11px] text-slate-500">sha256 {x.sha256.slice(0, 16)}…</span>}
                  </p>
                  {x.explained_by ? (
                    <p className="text-xs text-emerald-700">explained by decision {x.explained_by.slice(0, 8)}</p>
                  ) : (
                    <div className="mt-1 flex gap-2">
                      <input
                        value={reason[x.id] ?? ""}
                        onChange={(e) => setReason({ ...reason, [x.id]: e.target.value })}
                        placeholder="Why this difference is intended…"
                        className="flex-1 rounded border border-slate-300 px-2 py-1 text-xs"
                      />
                      <button
                        disabled={!reason[x.id]}
                        onClick={() => explain.mutate(x)}
                        className="rounded border border-slate-300 px-2 py-1 text-xs disabled:opacity-50"
                      >
                        Explain
                      </button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-[11px] text-slate-400">
            Manifest {report.manifest_hash.slice(0, 16)}… · {new Date(report.at).toLocaleString()} · stored immutably
          </p>
        </>
      ) : (
        <Empty>No report yet.</Empty>
      )}
      <div className="mt-3 border-t border-slate-100 pt-3">
        <JsonArea label="Export manifest to compare" value={manifest} onChange={setManifest} rows={4} />
        {run.isError && <p className="mt-1 text-sm text-red-600">{errorText(run.error)}</p>}
        <button
          disabled={parse(manifest) === undefined || run.isPending}
          onClick={() => run.mutate()}
          className="mt-2 rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium disabled:opacity-50"
        >
          Run the reconciliation
        </button>
      </div>
    </Card>
  );
}

/** The pilot's 30-day way back (§17.7): export what ARGUS changed since W,
 * for the source's administrators to apply by hand, then return the domain. */
function PilotReversion({ d, onDone }: { d: DomainDetail; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const [exported, setExported] = useState(false);
  const exportIt = useMutation({
    mutationFn: () => domainsApi.reversionExport(d.id),
    onSuccess: (report) => {
      const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${d.id}-changes-since-W.json`;
      a.click();
      setExported(true);
    },
  });
  const revert = useMutation({ mutationFn: () => domainsApi.revert(d.id, reason), onSuccess: onDone });
  return (
    <div className="mt-3 rounded border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
      <p className="font-medium">Pilot reversion window (30 days after the exit)</p>
      <p className="mt-0.5">
        ARGUS never writes to Jira. If the pilot is abandoned, export the change report, have the Jira administrators
        apply it, then return the domain to T1.
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        <button onClick={() => exportIt.mutate()} className="rounded border border-amber-300 bg-white px-2 py-1">
          Export the change report
        </button>
        <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why the pilot is abandoned" className="min-w-[14rem] flex-1 rounded border border-amber-300 px-2 py-1" />
        <button
          disabled={!exported || !reason}
          onClick={() => revert.mutate()}
          className="rounded bg-amber-700 px-2 py-1 text-white disabled:opacity-50"
        >
          Return the domain to T1
        </button>
      </div>
      {(exportIt.error || revert.error) && <p className="mt-1 text-red-700">{errorText(exportIt.error ?? revert.error)}</p>}
    </div>
  );
}
