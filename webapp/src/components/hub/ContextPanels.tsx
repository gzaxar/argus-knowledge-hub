/** The walls between the three sections, taken down: each record shows the
 * other two kinds next to it. An asset shows its tickets and the knowledge
 * that applies to it; a ticket shows its equipment, the procedures for that
 * equipment and what else is open on it; a document shows where it applies
 * and what is currently broken there. All from /v1/hub (one call each). */
import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { documentsApi, hubApi } from "../../api/client";
import type { AssetContext, HubDocument } from "../../api/hubTypes";
import { AccessPointPanel, InvolvedTickets, SegmentPortPanel, TicketAttribution } from "./ConnectivityPanels";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { auditApi } from "../../api/client";
import { AuditTrail, EquipmentPanel, PositionSpares } from "./EquipmentPanels";
import { errorText, INSTALLABLE, InstallationHistory, NOT_EQUIPMENT, ProvenancePanel } from "./LedgerPanels";
import { Card, DocumentRow, Empty, StatTile, Tabs, TicketRow, VIA_META } from "./ui";

type AssetTab = "service" | "knowledge" | "connections" | "installations" | "equipment" | "provenance";
const ASSET_TABS: AssetTab[] = ["service", "knowledge", "connections", "installations", "equipment", "provenance"];

export function AssetContextPanel({ assetUid }: { assetUid: string }) {
  const location = useLocation();
  const initial = (location.hash.replace("#", "") as AssetTab) || "service";
  const [tab, setTab] = useState<AssetTab>(ASSET_TABS.includes(initial) ? initial : "service");
  const ctx = useQuery({
    queryKey: ["hub-asset", assetUid],
    queryFn: () => hubApi.assetContext(assetUid),
    // While derived links are catching up with an edit, look again shortly.
    refetchInterval: (q) => (q.state.data?.processing ? 2000 : false),
  });

  useEffect(() => {
    const h = location.hash.replace("#", "") as AssetTab;
    if (ASSET_TABS.includes(h)) setTab(h);
  }, [location.hash]);

  if (ctx.isLoading) return <div className="mt-6 h-40 animate-pulse rounded-lg bg-slate-100" />;
  if (!ctx.data) return null;
  const c = ctx.data;

  const byVia = (["asset", "product", "type", "service"] as const)
    .map((via) => ({ via, docs: c.documents.filter((d) => d.via === via) }))
    .filter((g) => g.docs.length);

  return (
    <section className="mt-6" aria-label="Asset 360°">
      {c.merged && <MergedBanner merged={c.merged} assetUid={assetUid} />}
      {(c.processing || c.restricted) && (
        <div className="mb-2 flex flex-wrap gap-2">
          {c.processing && (
            <span className="rounded bg-sky-50 px-2 py-0.5 text-xs text-sky-800 ring-1 ring-inset ring-sky-200">
              Deriving — links, counts and the graph are catching up with the latest edit
            </span>
          )}
          {c.restricted && (
            <span className="rounded bg-red-50 px-2 py-0.5 text-xs text-red-800 ring-1 ring-inset ring-red-200">
              Restricted: {c.restricted.replace(/_/g, " ")} — hidden from anyone without that grant
            </span>
          )}
        </div>
      )}
      {c.type_path.length > 1 && (
        <p className="mb-2 text-xs text-slate-500">
          Type: {c.type_path.join(" › ")}
        </p>
      )}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile
          label="Open tickets"
          value={c.access.tickets ? c.stats.open_tickets : "—"}
          tone={c.stats.open_tickets ? "amber" : "slate"}
          hint={c.access.tickets ? `${c.stats.tickets} in total${c.stats.external_tickets ? `, ${c.stats.external_tickets} in Jira archive` : ""}` : "No access to tickets"}
        />
        <StatTile
          label="Applicable documents"
          value={c.access.documents ? c.stats.documents : "—"}
          tone="emerald"
          hint={c.access.documents ? "This asset, its product and its type" : "No access to documents"}
        />
        <StatTile
          label="Reviews overdue"
          value={c.access.documents ? c.stats.documents_overdue : "—"}
          tone={c.stats.documents_overdue ? "red" : "slate"}
          hint="Among its documents"
        />
        <StatTile label="Connections" value={c.stats.relations} tone="indigo" hint="Relations in the graph" />
      </div>

      <div className="mt-4 rounded-lg border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-2 px-4 pt-2">
          <Tabs<AssetTab>
            value={tab}
            onChange={setTab}
            tabs={[
              { key: "service", label: "Service", count: c.stats.open_tickets, alert: c.stats.open_tickets > 0 },
              { key: "knowledge", label: "Knowledge", count: c.stats.documents, alert: c.stats.documents_overdue > 0 },
              { key: "connections", label: "Connections", count: c.stats.relations },
              {
                key: "installations",
                label:
                  c.asset.type === "Access Point"
                    ? "Address history"
                    : c.asset.type === "Bus Segment"
                      ? "Port"
                      : INSTALLABLE.has(c.asset.type)
                        ? "Installed units"
                        : "Installations",
              },
              ...(NOT_EQUIPMENT.has(c.asset.type)
                ? []
                : [{ key: "equipment" as AssetTab, label: "Lifecycle & custody" }]),
              { key: "provenance", label: "Provenance" },
            ]}
          />
          <div className="flex gap-2 pb-2">
            <Link
              to={`/tickets/new?asset_uid=${encodeURIComponent(assetUid)}`}
              className="rounded-md bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-700"
            >
              Report an issue
            </Link>
            <Link
              to={`/documents/new?relate_asset=${encodeURIComponent(assetUid)}`}
              className="rounded-md border border-emerald-300 px-3 py-1.5 text-xs font-medium text-emerald-700 hover:bg-emerald-50"
            >
              Write a document
            </Link>
          </div>
        </div>

        <div className="px-4 pb-3">
          {tab === "service" &&
            (!c.access.tickets ? (
              <Empty>You do not have access to tickets in this workspace.</Empty>
            ) : c.tickets.length === 0 && c.external_tickets.length === 0 ? (
              <Empty>No ticket has been raised on this asset.</Empty>
            ) : (
              <>
                <ul className="divide-y divide-slate-100">
                  {c.tickets.map((t) => (
                    <TicketRow key={t.uid} ticket={t} />
                  ))}
                </ul>
                {c.external_tickets.length > 0 && (
                  <div className="mt-3 border-t border-slate-100 pt-2">
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                      Jira archive (read-only)
                    </p>
                    <ul className="mt-1 divide-y divide-slate-50">
                      {c.external_tickets.map((t) => (
                        <li key={t.key} className="flex items-center justify-between gap-3 py-1.5 text-sm">
                          <span className="min-w-0 truncate">
                            <span className="mr-2 font-mono text-xs text-slate-500">{t.key}</span>
                            {t.url ? (
                              <a href={t.url} target="_blank" rel="noreferrer" className="text-slate-700 hover:underline">
                                {t.summary}
                              </a>
                            ) : (
                              t.summary
                            )}
                          </span>
                          <span className="shrink-0 text-xs text-slate-500">{t.status}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            ))}

          {tab === "service" && c.access.tickets && <InvolvedTickets uid={assetUid} />}

          {tab === "knowledge" &&
            (!c.access.documents ? (
              <Empty>You do not have access to documents in this workspace.</Empty>
            ) : byVia.length === 0 ? (
              <Empty>
                No procedure, manual or report applies to this asset yet. Documents linked to its type or product model
                appear here automatically.
              </Empty>
            ) : (
              <div className="space-y-3 pt-1">
                {byVia.map((g) => (
                  <div key={g.via}>
                    <p className="mt-2 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                      {VIA_META[g.via].explain}
                    </p>
                    <ul className="divide-y divide-slate-100">
                      {g.docs.map((d) => (
                        <DocumentRow key={d.uid} doc={d} />
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            ))}

          {tab === "installations" &&
            (c.asset.type === "Access Point" ? (
              <AccessPointPanel uid={assetUid} />
            ) : c.asset.type === "Bus Segment" ? (
              <SegmentPortPanel uid={assetUid} />
            ) : (
              <>
                <InstallationHistory uid={assetUid} type={c.asset.type} />
                {INSTALLABLE.has(c.asset.type) && (
                  <div className="mt-3">
                    <PositionSpares uid={assetUid} />
                  </div>
                )}
              </>
            ))}
          {tab === "equipment" && <EquipmentPanel uid={assetUid} />}
          {tab === "provenance" && (
            <>
              <ProvenancePanel uid={assetUid} />
              <AuditTrail uid={assetUid} />
            </>
          )}

          {tab === "connections" &&
            (c.relations.items.length === 0 ? (
              <Empty>No relations to other assets.</Empty>
            ) : (
              <ul className="divide-y divide-slate-100">
                {c.relations.items.map((n) => (
                  <li key={`${n.direction}-${n.relation}-${n.uid}`} className="flex items-center justify-between gap-3 py-2 text-sm">
                    <span className="min-w-0">
                      <span className="mr-2 rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600">
                        {n.direction === "out" ? n.relation : `← ${n.relation}`}
                      </span>
                      <Link to={`/assets/${n.uid}`} className="font-medium text-slate-900 hover:text-indigo-700">
                        {n.name}
                      </Link>
                      <span className="ml-2 text-xs text-slate-500">{n.type}</span>
                    </span>
                    <span className="shrink-0 font-mono text-xs text-slate-400">{n.key}</span>
                  </li>
                ))}
                {c.relations.total > c.relations.items.length && (
                  <li className="py-2 text-xs text-slate-500">
                    {c.relations.total - c.relations.items.length} more —{" "}
                    <Link to="/graph" className="underline">
                      open in the knowledge graph
                    </Link>
                  </li>
                )}
              </ul>
            ))}
        </div>
      </div>
    </section>
  );
}

export function TicketContextPanel({ ticketUid }: { ticketUid: string }) {
  const ctx = useQuery({ queryKey: ["hub-ticket", ticketUid], queryFn: () => hubApi.ticketContext(ticketUid) });
  if (!ctx.data) return null;
  const c = ctx.data;
  return (
    <div className="space-y-4">
      <Card title="Equipment">
        {c.assets.length === 0 ? (
          <Empty>
            This ticket is not linked to any equipment. Linking it makes the procedures for that equipment appear here,
            and the ticket appear on the equipment.
          </Empty>
        ) : (
          <ul className="divide-y divide-slate-100">
            {c.assets.map((a) => (
              <li key={a.uid} className="py-2">
                <Link to={`/assets/${a.uid}`} className="text-sm font-medium text-slate-900 hover:text-indigo-700">
                  {a.name}
                </Link>
                <p className="text-xs text-slate-500">
                  <span className="font-mono">{a.key}</span> · {a.type}
                  {a.lifecycle ? ` · ${a.lifecycle}` : ""}
                </p>
              </li>
            ))}
          </ul>
        )}
        <TicketAttribution ticketUid={ticketUid} />
      </Card>
      {c.access.documents && c.assets.length > 0 && (
        <Card title="Relevant knowledge" action={<span className="text-xs text-slate-400">for this equipment</span>}>
          {c.suggested_documents.length === 0 ? (
            <Empty>
              No procedure or manual is linked to this equipment, its product or its type. A document linked to
              the ticket itself is listed with what the ticket is about.
            </Empty>
          ) : (
            <ul className="divide-y divide-slate-100">
              {c.suggested_documents.map((d: HubDocument) => (
                <DocumentRow
                  key={d.uid}
                  doc={d}
                  extra={
                    d.for_assets && d.for_assets.length > 0 && c.assets.length > 1 ? (
                      <span>for {d.for_assets.map((a) => a.name).join(", ")}</span>
                    ) : undefined
                  }
                />
              ))}
            </ul>
          )}
        </Card>
      )}
      {c.concurrent_tickets.length > 0 && (
        <Card title="Also open on this equipment">
          <ul className="divide-y divide-slate-100">
            {c.concurrent_tickets.map((t) => (
              <TicketRow key={t.uid} ticket={t} />
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

export function DocumentContextPanel({ documentUid, canLink = false }: { documentUid: string; canLink?: boolean }) {
  const queryClient = useQueryClient();
  const ctx = useQuery({ queryKey: ["hub-document", documentUid], queryFn: () => hubApi.documentContext(documentUid) });
  const link = useMutation({
    mutationFn: (assetUid: string) =>
      documentsApi.addRelation(documentUid, { to_type: "asset", to_uid: assetUid, relation_type: "describes" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["hub-document", documentUid] });
      queryClient.invalidateQueries({ queryKey: ["document-relations", documentUid] });
    },
  });
  if (!ctx.data) return null;
  const c = ctx.data;
  const nothing = c.assets.length === 0 && c.types.length === 0 && c.instances.length === 0;
  const named = canLink ? c.named ?? [] : [];
  return (
    <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card title="Applies to">
        {named.length > 0 && (
          <div className="mb-2 rounded border border-indigo-100 bg-indigo-50/60 p-2" data-testid="named-in-text">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-indigo-700">Named in the text</p>
            <p className="text-[11px] text-slate-500">Found in the inventory by key, tag or name. Nothing is linked until you
              say so.</p>
            <ul className="mt-1 space-y-1 text-sm">
              {named.map((a) => (
                <li key={a.uid} className="flex items-center justify-between gap-2">
                  <span>
                    <Link to={`/assets/${a.uid}`} className="font-medium text-slate-900 hover:underline">{a.name}</Link>
                    <span className="ml-2 text-xs text-slate-500">{a.type} · by {a.matched_on}</span>
                  </span>
                  <button type="button" onClick={() => link.mutate(a.uid)} disabled={link.isPending}
                          className="rounded border border-indigo-300 bg-white px-2 py-0.5 text-xs text-indigo-700 hover:bg-indigo-50">
                    Link
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {nothing ? (
          <Empty>
            Not linked to any asset or type yet. Link it to an object type or a product model and it appears on every
            matching asset.
          </Empty>
        ) : (
          <div className="space-y-2 py-1 text-sm">
            {c.types.map((t) => (
              <p key={t.uid} className="flex items-center justify-between">
                <span>
                  <span className="mr-2 rounded bg-cyan-50 px-1.5 py-0.5 text-[10px] font-medium text-cyan-700">Type</span>
                  <Link to={`/schemas/${t.uid}`} className="font-medium text-slate-900 hover:underline">
                    {t.name}
                  </Link>
                </span>
                <span className="text-xs text-slate-500">{t.assets} asset{t.assets === 1 ? "" : "s"}</span>
              </p>
            ))}
            {c.assets.map((a) => (
              <p key={a.uid}>
                <span className="mr-2 rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700">Asset</span>
                <Link to={`/assets/${a.uid}`} className="font-medium text-slate-900 hover:underline">
                  {a.name}
                </Link>
                <span className="ml-2 text-xs text-slate-500">{a.type}</span>
              </p>
            ))}
            {c.instances.length > 0 && (
              <div className="pt-1">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                  Units of that product ({c.instances.length})
                </p>
                <p className="mt-1 flex flex-wrap gap-1.5">
                  {c.instances.map((a) => (
                    <Link
                      key={a.uid}
                      to={`/assets/${a.uid}`}
                      className="rounded border border-slate-200 px-1.5 py-0.5 text-xs text-slate-700 hover:bg-slate-50"
                    >
                      {a.name}
                    </Link>
                  ))}
                </p>
              </div>
            )}
          </div>
        )}
      </Card>
      <Card title="Open tickets where it applies">
        {!c.access.tickets ? (
          <Empty>You do not have access to tickets in this workspace.</Empty>
        ) : c.open_tickets.length === 0 ? (
          <Empty>Nothing is open on the equipment this document covers.</Empty>
        ) : (
          <ul className="divide-y divide-slate-100">
            {c.open_tickets.map((t) => (
              <TicketRow key={t.uid} ticket={t} />
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function MergedBanner({ merged, assetUid }: { merged: NonNullable<AssetContext["merged"]>; assetUid: string }) {
  const queryClient = useQueryClient();
  const undo = useMutation({
    mutationFn: () => auditApi.unmerge(merged.decision_id!, "undone from the merged record"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["hub-asset", assetUid] }),
  });
  return (
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
      <span>
        Merged into{" "}
        {merged.into ? (
          <Link to={`/assets/${merged.into.uid}`} className="font-medium underline">
            {merged.into.name}
          </Link>
        ) : (
          "another record"
        )}
        . This record is kept as a tombstone; its references resolve to the survivor.
      </span>
      {merged.decision_id && (
        <button onClick={() => undo.mutate()} className="rounded border border-amber-300 bg-white px-3 py-1 text-xs">
          Undo the merge
        </button>
      )}
      {undo.isError && <span className="w-full text-xs text-red-700">{errorText(undo.error)}</span>}
    </div>
  );
}
