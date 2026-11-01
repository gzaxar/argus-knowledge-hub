import type { TransferPreview } from "../api/client";

/** The reconciliation report of a transfer (POST /v1/transfers/preview): what goes, what stays where it is, what
 *  would no longer resolve. Read before the transfer runs; nothing has changed. */
export function TransferReport({ report }: { report: TransferPreview }) {
  const plans = report.indoors.plans;
  const attributeRefs = report.references.filter((r) => r.kind === "attribute");
  const relations = report.references.filter((r) => r.kind === "relation");
  const global = report.records.filter((r) => r.is_global);
  const notIfLocal = attributeRefs.filter((r) => r.resolves_after && r.resolves_if_not_global === false);
  return (
    <section aria-label="Transfer report" className="space-y-2 rounded border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
      <p className={report.clean ? "font-medium text-emerald-700" : "font-medium text-amber-800"}>
        {report.clean ? "Nothing would break." : `${report.problems.length} thing${report.problems.length === 1 ? "" : "s"} to look at before it runs.`}
      </p>
      <p>
        {report.mode === "move" ? "Moves" : "Copies"} {report.records.length} record{report.records.length === 1 ? "" : "s"}
        {report.mode === "move" && " — the same records, with the same ids and keys, so references to them hold"}:{" "}
        {report.records.map((r) => r.name).join(", ")}.
        {report.mode === "move" && report.records.some((r) => r.site_shared_after) &&
          " Its places become the site's, shared with its facilities."}
      </p>
      {(report.indoors.levels.length > 0 || plans.length > 0) && (
        <p>
          With {report.indoors.levels.length} floor{report.indoors.levels.length === 1 ? "" : "s"} and {plans.length} plan
          {plans.length === 1 ? "" : "s"}{plans.some((p) => p.placed_on_map) && ", kept where they are on the map"}
          {plans.some((p) => !p.files_present) && <span className="text-red-700"> — a plan's file is missing</span>}.
        </p>
      )}
      {report.placements.length > 0 && (
        <p>
          Placements of these records: {report.placements.filter((p) => p.eligible).length} carried
          {report.placements.some((p) => !p.eligible) &&
            <span className="text-amber-800">, {report.placements.filter((p) => !p.eligible).length} would end</span>}.
        </p>
      )}
      {report.placed_inside.length > 0 && (
        <div>
          <p>Records of other workspaces placed in them:</p>
          <ul className="ml-4 list-disc">
            {report.placed_inside.map((x) => (
              <li key={x.record.uid} className={x.keeps_placement ? "" : "text-amber-800"}>
                {x.record.name} <span className="text-slate-500">({x.record.workspace_id})</span>
                {x.keeps_placement ? " — stays placed" : ` — would lose its placement: ${x.why}`}
              </li>
            ))}
          </ul>
        </div>
      )}
      {attributeRefs.length > 0 && (
        <div>
          <p>Records naming them:</p>
          <ul className="ml-4 list-disc">
            {attributeRefs.map((r) => (
              <li key={`${r.from?.uid}:${r.to}`} className={r.resolves_after ? "" : "text-red-700"}>
                {r.from?.name} <span className="text-slate-500">({r.from?.workspace_id}, {r.attributes?.join(", ")})</span>
                {r.resolves_after ? " — still resolves" : ` — would no longer resolve: ${r.why}`}
              </li>
            ))}
          </ul>
        </div>
      )}
      {relations.length > 0 && (
        <p className={report.mode === "move" ? "text-amber-800" : ""}>
          {relations.length} relation{relations.length === 1 ? "" : "s"} with records staying behind
          {report.mode === "move" ? " would be dropped (a move does not keep a relation across workspaces)" : " stay with the originals"}:{" "}
          {relations.map((r) => `${r.relation_type} ${r.from?.name}`).join(", ")}.
        </p>
      )}
      {global.length > 0 && report.mode === "move" && (
        <p className="text-slate-600">
          {global.map((r) => r.name).join(", ")} {global.length === 1 ? "is" : "are"} global: every workspace sees
          {global.length === 1 ? " it" : " them"}.{" "}
          {notIfLocal.length === 0
            ? "Every record naming them would still reach them through the site if they stopped being global."
            : `If they stopped being global, ${notIfLocal.map((r) => `${r.from?.name} (${r.from?.workspace_id})`).join(", ")} would no longer reach them.`}
        </p>
      )}
      {report.labels_carried > 0 && <p>{report.labels_carried} label{report.labels_carried === 1 ? "" : "s"} go with them.</p>}
    </section>
  );
}
