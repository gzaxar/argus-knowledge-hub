import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { FullPage, useFullPage } from "../../components/FullPage";
import { indoorApi, type FloorPlanShow } from "../../api/client";
import { PlanView, type PlanLine, type PlanPin } from "../../components/PlanView";

const COLOURS = ["#dc2626", "#2563eb", "#16a34a", "#9333ea", "#ea580c", "#0891b2"];

type Row = FloorPlanShow["records"][number];

const shownAs = (r: Row) => (r.spot?.via ? `${r.key || r.name} (in ${r.spot.via.key || r.spot.via.name})` : r.key || r.name);

/** Records on their floor plans, from a link such as Ask's "Show … on the floor plan": each at its own point, or —
 *  a converter in a rack — at its rack's, said as such; with how far and which way each is from the first. */
export function FloorPlanPage() {
  const [params] = useSearchParams();
  const wanted = (params.get("show") ?? "").split(",").map((s) => s.trim()).filter(Boolean);
  const q = useQuery({ queryKey: ["floor-plan-show", wanted.join(",")], queryFn: () => indoorApi.show(wanted),
                       enabled: wanted.length > 0 });
  const [full, setFull] = useState<string | null>(null);

  if (wanted.length === 0) return <p className="p-6 text-sm text-slate-500">Nothing to show: no record was named.</p>;
  if (q.isLoading) return <p className="p-6 text-sm text-slate-500">Loading the floor plans…</p>;
  if (q.isError || !q.data) return <p className="p-6 text-sm text-red-600">The floor plans could not be loaded.</p>;

  const { records, plans } = q.data;
  const colour = new Map(records.map((r, i) => [r.uid, COLOURS[i % COLOURS.length]]));
  const first = records.find((r) => r.spot);
  const unplaced = records.filter((r) => !r.spot);

  return (
    <div className="space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-lg font-semibold text-slate-900">On the floor plan</h1>
        <ul className="mt-2 space-y-1 text-sm">
          {records.map((r) => (
            <li key={r.uid} className="flex flex-wrap items-baseline gap-x-2">
              <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: colour.get(r.uid) }} aria-hidden="true" />
              <Link to={`/assets/${r.uid}`} className="font-medium text-indigo-700 hover:underline">{r.key || r.name}</Link>
              <span className="text-slate-600">{r.name}</span>
              {r.spot?.via && (
                <span className="text-xs text-slate-500">
                  no point of its own: shown where its {r.spot.via.type.toLowerCase()}{" "}
                  <Link to={`/assets/${r.spot.via.uid}`} className="hover:underline">{r.spot.via.key || r.spot.via.name}</Link> is
                </span>
              )}
              {r.from_first && first && r.uid !== first.uid && (
                <span className="text-xs text-slate-700">
                  — {r.from_first.metres} m{r.from_first.direction && ` ${r.from_first.direction}`} of {first.key || first.name}
                </span>
              )}
              {!r.spot && <span className="text-xs text-amber-700">not on any floor plan</span>}
            </li>
          ))}
        </ul>
      </div>

      {plans.map((plan) => {
        const here = records.filter((r) => r.spot?.plan.uid === plan.uid);
        const pins: PlanPin[] = here.map((r) => ({ id: r.uid, x: r.spot!.x, y: r.spot!.y, label: shownAs(r),
                                                   colour: colour.get(r.uid), highlight: true }));
        const origin = first?.spot?.plan.uid === plan.uid ? first : null;
        const lines: PlanLine[] = origin
          ? here.filter((r) => r.uid !== origin.uid && r.from_first).map((r) => ({
              id: `${origin.uid}-${r.uid}`, from: { x: origin.spot!.x, y: origin.spot!.y }, to: { x: r.spot!.x, y: r.spot!.y },
              label: `${r.from_first!.metres} m` }))
          : [];
        const legend = (
          <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
            {here.map((r) => (
              <li key={r.uid} className="flex items-center gap-1">
                <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: colour.get(r.uid) }} aria-hidden="true" />
                <span className="font-medium">{r.key || r.name}</span>
                {r.from_first && <span className="text-slate-500">{r.from_first.metres} m{r.from_first.direction ? ` ${r.from_first.direction}` : ""}</span>}
              </li>
            ))}
          </ul>
        );
        return (
          <section key={plan.uid} aria-label={plan.name} className="rounded-lg border border-slate-200 bg-white p-3">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-slate-900">
                {plan.name}{plan.level && <span className="font-normal text-slate-500"> · {plan.level.name}</span>}
              </h2>
              {full !== plan.uid && (
                <button type="button" onClick={() => setFull(plan.uid)}
                        className="rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50">Full screen</button>
              )}
            </div>
            <FullPage open={full === plan.uid} title={plan.name} onClose={() => setFull(null)}>
              {full === plan.uid && legend}
              <Plan plan={plan} pins={pins} lines={lines} />
            </FullPage>
          </section>
        );
      })}
      {unplaced.length > 0 && plans.length === 0 && (
        <p className="text-sm text-slate-500">None of them is on a floor plan, nor is any place they are in.</p>
      )}
    </div>
  );
}

/** The plan, zoomed to the records shown; as tall as the screen in a full-screen window. */
function Plan({ plan, pins, lines }: { plan: FloorPlanShow["plans"][number]; pins: PlanPin[]; lines: PlanLine[] }) {
  const full = useFullPage();
  return (
    <PlanView planUid={plan.uid} width={plan.width_px} height={plan.height_px} pins={pins} lines={lines}
              northDeg={plan.north_deg} focus={pins.map((p) => ({ x: p.x, y: p.y }))}
              className={full ? "h-[calc(100vh-7rem)] min-h-[20rem]" : "h-[60vh] min-h-[18rem]"} />
  );
}
