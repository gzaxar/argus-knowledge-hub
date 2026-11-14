import { AssistantProposals } from "./AssistantProposals";
import { askText } from "../../lib/dialogs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ApiError, intakeApi, ledgerApi } from "../../api/client";
import type { Decision, LedgerReviewProposal, RecordBrief, ReviewQueue } from "../../api/ledgerTypes";
import { Card, Empty, StatTile } from "../../components/hub/ui";
import { formatTemporal } from "../../components/hub/LedgerPanels";
import { QueueAgeingCard } from "../../components/hub/QueueAgeing";

/**
 * Everything waiting on a person: conflicts between sources and confirmations,
 * inferred facts that need a yes or no, installations found from inventory
 * links, and source revisions held because they would retire too much. Every
 * button here records a decision in the ledger; nothing is overwritten.
 */
const CONFLICT_TEXT: Record<string, { title: string; explain: string }> = {
  confirmed_vs_confirmed: {
    title: "Two people confirmed different values",
    explain: "The earlier confirmation still applies. Pick the value that is right; the other is superseded, both stay on record.",
  },
  authority_vs_authority: {
    title: "Two authoritative sources disagree",
    explain: "The value seen first still applies. Confirm the right one.",
  },
  source_vs_confirmed: {
    title: "A source disagrees with a confirmed value",
    explain: "The confirmed value stays. If the source is right, change the value on the record.",
  },
  contributory_disagreement: {
    title: "Sources disagree",
    explain: "The most recent observation is used for now.",
  },
  possible_overlap: {
    title: "Installations may overlap",
    explain: "Their dates are not precise enough to tell. Give an exact date to one of them.",
  },
  port_confirmation_required: {
    title: "A bus segment needs its port confirmed",
    explain: "The segment carries a safety class, or the only match is not backed by the IT registry. Pick the port for the unit installed now; the choice applies to this installation only.",
  },
  port_mapping_unresolved: {
    title: "No single port matches a bus segment",
    explain: "The unit installed now has no port, or several, that meet the requirement. Fix the IT registry or confirm the port.",
  },
  port_map_invalid: {
    title: "A confirmed port is no longer compatible",
    explain: "The port confirmed for this installation fails a hard check. A confirmation never overrides compatibility.",
  },
  merge_installation_overlap: {
    title: "A merge left one unit installed in two places at once",
    explain: "The merged records were both installed at overlapping times. End one of the installations, or undo the merge from the merged record.",
  },
  identity_candidate: {
    title: "Two records may be the same thing",
    explain: "They share a strong identifier. Nothing is merged automatically: merge them, or say they are different.",
  },
  retirement_blocked: {
    title: "A source dropped a position that is still occupied",
    explain: "The position stays active because a confirmed installation is current. End the installation if the unit was removed.",
  },
};

function RecordLink({ r }: { r: RecordBrief | null }) {
  if (!r) return <span className="text-slate-400">—</span>;
  return (
    <Link to={`/assets/${r.uid}`} className="font-medium text-slate-900 hover:underline">
      {r.name}
      <span className="ml-1.5 font-mono text-[11px] font-normal text-slate-400">{r.key}</span>
    </Link>
  );
}

function show(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v;
  if (typeof v === "object" && v && "ref" in (v as object)) return String((v as { ref: string }).ref);
  if (typeof v === "object" && v && "type" in (v as object)) return `a ${(v as { type: string }).type}`;
  return JSON.stringify(v);
}

export function ReviewQueuePage() {
  const queryClient = useQueryClient();
  const review = useQuery({ queryKey: ["ledger-review"], queryFn: ledgerApi.review, refetchInterval: 30_000 });
  const done = () => {
    queryClient.invalidateQueries({ queryKey: ["ledger-review"] });
    queryClient.invalidateQueries({ queryKey: ["installations"] });
    queryClient.invalidateQueries({ queryKey: ["hub-asset"] });
  };
  const decide = useMutation({ mutationFn: (batch: Decision[]) => ledgerApi.decide(batch), onSuccess: done });
  const confirmInst = useMutation({ mutationFn: (uid: string) => ledgerApi.confirmInstallation(uid), onSuccess: done });
  const rejectInst = useMutation({ mutationFn: (uid: string) => ledgerApi.rejectInstallation(uid), onSuccess: done });
  const approve = useMutation({ mutationFn: (id: string) => ledgerApi.approveRevision(id), onSuccess: done });
  const rejectRev = useMutation({ mutationFn: (id: string) => ledgerApi.rejectRevision(id), onSuccess: done });
  const portMap = useMutation({
    mutationFn: (v: { segment: string; installation: string; port: string }) =>
      ledgerApi.confirmPortMap(v.segment, { installation_uid: v.installation, port_uid: v.port }),
    onSuccess: done,
  });
  const merge = useMutation({
    mutationFn: (v: { survivor: string; loser: string }) =>
      ledgerApi.merge({ survivor_uid: v.survivor, loser_uid: v.loser, reason: "merged from the review queue" }),
    onSuccess: done,
  });
  const dismiss = useMutation({
    mutationFn: (v: { records: string[]; kind: "reject_candidate" | "confirm_new" }) => ledgerApi.dismissCandidate(v),
    onSuccess: done,
  });
  const error = [decide, confirmInst, rejectInst, approve, rejectRev, portMap, merge, dismiss].find((m) => m.isError)
    ?.error;

  if (review.isLoading) return <p className="text-sm text-slate-500">Loading the review queue…</p>;
  if (!review.data) return <p className="text-sm text-red-600">The review queue could not be loaded.</p>;
  const q: ReviewQueue = review.data;
  const blocking = q.conflicts.filter((c) => c.severity === "blocking");
  const other = q.conflicts.filter((c) => c.severity !== "blocking");

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Review queue</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          Decisions only a person can make. Each one is recorded with its author; nothing is overwritten.
        </p>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <StatTile label="Blocking conflicts" value={q.counts.blocking} tone={q.counts.blocking ? "red" : "slate"} />
        <StatTile label="Held revisions" value={q.counts.held_revisions} tone={q.counts.held_revisions ? "red" : "slate"} />
        <StatTile label="Installations to confirm" value={q.counts.installation_proposals} tone="amber" />
        <StatTile label="Facts to confirm" value={q.counts.proposals} tone="amber" />
        <StatTile label="Other conflicts" value={other.length} />
      </div>
      <QueueAgeingCard />
      <AssistantProposals />
      {error && (
        <p className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error instanceof ApiError ? JSON.stringify((error.body as { detail?: unknown })?.detail) : "The decision failed."}
        </p>
      )}

      {q.held_revisions.length > 0 && (
        <Card title="Source revisions held before they change anything">
          <ul className="divide-y divide-slate-100">
            {q.held_revisions.map((h) => (
              <li key={h.revision_id} className="flex flex-wrap items-start justify-between gap-3 py-2.5">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-900">
                    {h.stream_id} <span className="font-mono text-xs text-slate-500">@ {h.revision.slice(0, 12)}</span>
                  </p>
                  <ul className="mt-0.5 list-disc pl-5 text-xs text-slate-600">
                    {h.reasons.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                </div>
                <div className="flex gap-2">
                  <button onClick={() => approve.mutate(h.revision_id)} className="rounded bg-slate-900 px-3 py-1.5 text-xs font-medium text-white">
                    Approve and publish
                  </button>
                  <button onClick={() => rejectRev.mutate(h.revision_id)} className="rounded border border-slate-300 px-3 py-1.5 text-xs">
                    Reject revision
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title="Conflicts">
        {blocking.length + other.length === 0 ? (
          <Empty>No conflicts.</Empty>
        ) : (
          <ul className="divide-y divide-slate-100">
            {[...blocking, ...other].map((c) => {
              const text = CONFLICT_TEXT[c.type] ?? { title: c.type, explain: "" };
              const values = (c.detail.values as unknown[] | undefined) ?? [];
              const decisions = (c.detail.decisions as string[] | undefined) ?? [];
              return (
                <li key={c.conflict_id} className="py-3">
                  <div className="flex flex-wrap items-baseline gap-2">
                    {c.severity === "blocking" && (
                      <span className="rounded bg-red-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-red-700">blocking</span>
                    )}
                    <span className="text-sm font-medium text-slate-900">{text.title}</span>
                    <span className="text-sm text-slate-500">on</span>
                    <RecordLink r={c.record} />
                    {c.predicate && <span className="font-mono text-xs text-slate-500">{c.predicate}</span>}
                  </div>
                  <p className="mt-0.5 text-xs text-slate-500">{text.explain}</p>
                  {(c.type === "confirmed_vs_confirmed" || c.type === "authority_vs_authority") && c.record && (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {values.map((v, i) => (
                        <button
                          key={i}
                          onClick={() =>
                            decide.mutate([
                              decisions.length
                                ? { kind: "supersede", subject_uid: c.record!.uid, predicate: c.predicate!, member: c.member,
                                    value: v, supersedes: decisions }
                                : { kind: "confirm", subject_uid: c.record!.uid, predicate: c.predicate!, member: c.member, value: v },
                            ])
                          }
                          className="rounded border border-slate-300 bg-white px-3 py-1 text-xs hover:bg-slate-50"
                        >
                          Keep “{show(v)}”
                        </button>
                      ))}
                    </div>
                  )}
                  {c.type === "identity_candidate" && (
                    <IdentityActions
                      records={(c.detail.records as string[]) ?? []}
                      evidence={String(c.detail.evidence ?? "")}
                      onMerge={(survivor, loser) => merge.mutate({ survivor, loser })}
                      onDismiss={(kind) => dismiss.mutate({ records: c.detail.records as string[], kind })}
                    />
                  )}
                  {c.type.startsWith("port_") && c.record && (
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      {((c.detail.candidates as { port_uid: string; label: string }[] | undefined) ?? []).map((p) => (
                        <button
                          key={p.port_uid}
                          onClick={() =>
                            portMap.mutate({
                              segment: c.record!.uid,
                              installation: String(c.detail.installation_uid),
                              port: p.port_uid,
                            })
                          }
                          className="rounded border border-slate-300 bg-white px-3 py-1 text-xs hover:bg-slate-50"
                        >
                          Use {p.label}
                        </button>
                      ))}
                      {typeof c.detail.failed === "string" && (
                        <span className="text-xs text-red-700">failed: {c.detail.failed}</span>
                      )}
                      <Link to={`/assets/${c.record.uid}#installations`} className="text-xs text-indigo-700 hover:underline">
                        See why each port was ruled out
                      </Link>
                    </div>
                  )}
                  {c.type === "source_vs_confirmed" && (
                    <p className="mt-1 text-xs text-slate-600">
                      Confirmed: <span className="font-mono">{show(c.detail.confirmed)}</span> · sources say{" "}
                      <span className="font-mono">{((c.detail.sources as unknown[]) ?? []).map(show).join(", ")}</span>
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      <Card title="Installations found from inventory links">
        {q.installation_proposals.length === 0 ? (
          <Empty>No installation waits for confirmation.</Empty>
        ) : (
          <ul className="divide-y divide-slate-100">
            {q.installation_proposals.map((p) => (
              <li key={p.uid} className="flex flex-wrap items-center justify-between gap-3 py-2.5">
                <div className="text-sm">
                  <RecordLink r={p.asset} /> <span className="text-slate-500">at</span> <RecordLink r={p.position} />
                  <p className="text-xs text-slate-500">since {formatTemporal(p.valid_from, "from")}</p>
                </div>
                <div className="flex gap-2">
                  <button onClick={() => confirmInst.mutate(p.uid)} className="rounded bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white">
                    Confirm
                  </button>
                  <button onClick={() => rejectInst.mutate(p.uid)} className="rounded border border-slate-300 px-3 py-1.5 text-xs">
                    Reject
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Facts waiting for confirmation">
        {q.proposals.length === 0 ? (
          <Empty>No inferred or proposed fact waits for a decision.</Empty>
        ) : (
          <ul className="divide-y divide-slate-100">
            {q.proposals.map((p) => p.ai ? (
              <AIProposal key={p.claim_id} p={p} onDone={done} />
            ) : (
              <li key={p.claim_id} className="flex flex-wrap items-center justify-between gap-3 py-2.5">
                <div className="min-w-0 text-sm">
                  <RecordLink r={p.record} />{" "}
                  {p.match ? (
                    <>
                      is a <b>{p.match.model_name}</b>
                      {p.match.catalogue_id && <span className="font-mono text-xs text-slate-500"> ({p.match.catalogue_id})</span>}
                      <p className="text-xs text-slate-500">
                        GLPI says {p.match.glpi_manufacturer} / {p.match.glpi_model} ·{" "}
                        {p.match.match === "exact" ? "exact match" : `near match, score ${p.match.score}`}
                      </p>
                    </>
                  ) : (
                    <>
                      <span className="font-mono text-xs text-slate-500">{p.predicate}</span>{" "}
                      <span className="font-mono text-xs">{show(p.value)}</span>
                      <p className="text-xs text-slate-500">
                        {p.method} {p.rule_id ? `by ${p.rule_id}` : ""} · {p.stream_id}
                      </p>
                    </>
                  )}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => decide.mutate([{ kind: "accept", target: { claim_id: p.claim_id } }])}
                    className="rounded bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white"
                  >
                    Accept
                  </button>
                  <button
                    onClick={() => decide.mutate([{ kind: "reject", target: { claim_id: p.claim_id, scope: "fingerprint" } }])}
                    className="rounded border border-slate-300 px-3 py-1.5 text-xs"
                    title="Rejects this inference; the same rule will not propose it again"
                  >
                    Reject
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <RulesCard />

      {q.provisional_records.length > 0 && (
        <Card title="Provisional records">
          <ul className="flex flex-wrap gap-2 py-1">
            {q.provisional_records.map((r) => (
              <li key={r.uid}>
                <Link to={`/assets/${r.uid}#provenance`} className="rounded border border-slate-200 px-2 py-1 text-xs hover:bg-slate-50">
                  {r.name} <span className="text-slate-400">{r.type}</span>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

/** Which semantic rule runs for each inference family, and whether the
 * catalogue passes its signature check (§7.9). */
function RulesCard() {
  const rules = useQuery({ queryKey: ["ledger-rules"], queryFn: ledgerApi.rules });
  if (!rules.data) return null;
  // Only the rules a source of this workspace runs: an IT workspace has no magnet power supplies to infer.
  const active = rules.data.rules.filter((r) => r.active && r.used_here !== false);
  if (active.length === 0 && rules.data.check.length === 0) return null;
  return (
    <Card
      title="Inference rules in force"
      action={
        rules.data.check.length === 0 ? (
          <span className="text-xs text-emerald-700">catalogue check passes</span>
        ) : (
          <span className="text-xs text-red-700">{rules.data.check.length} catalogue problem(s)</span>
        )
      }
    >
      <ul className="divide-y divide-slate-100">
        {active.map((r) => (
          <li key={r.rule_id} className="py-2 text-sm">
            <span className="font-mono text-xs text-slate-900">{r.rule_id}</span>
            <span className="ml-2 text-xs text-slate-500">implementation {r.active_impl}</span>
            <p className="text-xs text-slate-600">{r.meaning}</p>
          </li>
        ))}
      </ul>
      {rules.data.check.map((e) => (
        <p key={e} className="text-xs text-red-700">
          {e}
        </p>
      ))}
    </Card>
  );
}

function IdentityActions({
  records,
  evidence,
  onMerge,
  onDismiss,
}: {
  records: string[];
  evidence: string;
  onMerge: (survivor: string, loser: string) => void;
  onDismiss: (kind: "reject_candidate" | "confirm_new") => void;
}) {
  const [a, b] = records;
  const one = useQuery({ queryKey: ["ledger-facts", a], queryFn: () => ledgerApi.facts(a), enabled: !!a });
  const two = useQuery({ queryKey: ["ledger-facts", b], queryFn: () => ledgerApi.facts(b), enabled: !!b });
  const ra = one.data?.record;
  const rb = two.data?.record;
  return (
    <div className="mt-2 space-y-2">
      <p className="text-xs text-slate-600">{evidence}</p>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <RecordLink r={ra ?? null} /> <span className="text-slate-400">and</span> <RecordLink r={rb ?? null} />
      </div>
      <div className="flex flex-wrap gap-2">
        {ra && rb && (
          <>
            <button onClick={() => onMerge(a, b)} className="rounded border border-slate-300 bg-white px-3 py-1 text-xs hover:bg-slate-50">
              Merge into {ra.key}
            </button>
            <button onClick={() => onMerge(b, a)} className="rounded border border-slate-300 bg-white px-3 py-1 text-xs hover:bg-slate-50">
              Merge into {rb.key}
            </button>
          </>
        )}
        <button onClick={() => onDismiss("confirm_new")} className="rounded border border-slate-300 px-3 py-1 text-xs">
          Both are real, different items
        </button>
        <button onClick={() => onDismiss("reject_candidate")} className="rounded border border-slate-300 px-3 py-1 text-xs">
          Not the same — dismiss
        </button>
      </div>
    </div>
  );
}


/** A value an assistant read from a file or a note (asset-model-revision §23.11): shown with where it was
 * read and what it would replace. Confirming makes it the reviewer's own statement; editing confirms the
 * corrected value; either way the proposal stays in the record's history. */
function AIProposal({ p, onDone }: { p: LedgerReviewProposal; onDone: () => void }) {
  const decide = useMutation({
    mutationFn: (v: { action: "confirm" | "edit" | "reject"; value?: unknown; reason?: string }) =>
      intakeApi.decide(p.claim_id, v.action, v.value, v.reason),
    onSuccess: onDone,
  });
  const ai = p.ai!;
  const field = p.predicate.replace(/^attr:/, "");
  return (
    <li className="flex flex-wrap items-start justify-between gap-3 py-2.5">
      <div className="min-w-0 text-sm">
        <RecordLink r={p.record} /> <span className="text-xs text-slate-500">{field}</span>{" "}
        <span className="font-medium">{show(p.value)}</span>
        {ai.current !== null && ai.current !== undefined && ai.current !== "" && (
          <span className="text-xs text-slate-400"> (now {show(ai.current)})</span>
        )}
        <p className="text-xs text-slate-500">
          <span className="rounded bg-violet-50 px-1 text-violet-700">AI proposal</span>{" "}
          {ai.confidence !== null ? `${Math.round(ai.confidence * 100)}% · ` : ""}
          {ai.quote ? (ai.grounded ? `read from “${ai.quote}”` : "could not point to where it read this") : "no evidence given"}
          {ai.model ? ` · ${ai.model}${ai.profile_id ? "" : " (not evaluated)"}` : ""}
          {ai.requested_by ? ` · asked by ${ai.requested_by}` : ""}
        </p>
        {decide.isError && <p className="text-xs text-red-600">{(decide.error as Error).message}</p>}
      </div>
      <div className="flex gap-2">
        <button onClick={() => decide.mutate({ action: "confirm" })}
                className="rounded bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white">Confirm</button>
        <button onClick={async () => {
                  const v = await askText(`The right value for ${field}:`, String(p.value ?? ""));
                  if (v) decide.mutate({ action: "edit", value: v });
                }}
                className="rounded border border-slate-300 px-3 py-1.5 text-xs">Correct</button>
        <button onClick={async () => {
                  const why = await askText("Why is it wrong?");
                  if (why) decide.mutate({ action: "reject", reason: why });
                }}
                className="rounded border border-slate-300 px-3 py-1.5 text-xs">Reject</button>
      </div>
    </li>
  );
}
