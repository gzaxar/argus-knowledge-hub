/** On a record's page: a rack shows its elevation and the way to its editor; a unit says where it is mounted. */
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { racksApi } from "../api/client";
import { RackElevation } from "./RackElevation";

function SectionCard({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
        {action}
      </div>
      <div className="mt-3">{children}</div>
    </div>
  );
}

export function RackCard({ uid, type }: { uid: string; type: string }) {
  const navigate = useNavigate();
  const isRack = type === "Rack";
  const rack = useQuery({ queryKey: ["rack", uid], queryFn: () => racksApi.get(uid), enabled: isRack });
  const where = useQuery({ queryKey: ["rack-of", uid], queryFn: () => racksApi.of(uid), enabled: !isRack });
  if (isRack) {
    if (!rack.data) return null;
    return (
      <SectionCard title="Rack elevation"
                   action={<Link to={`/racks/${uid}`} className="text-xs text-indigo-600 hover:underline">Edit the rack</Link>}>
        {rack.data.mountings.length === 0 ? (
          <p className="text-sm text-slate-500">
            Nothing is mounted yet. <Link to={`/racks/${uid}`} className="text-indigo-600 hover:underline">Open the editor</Link> to
            place what is in it.
          </p>
        ) : (
          <RackElevation view={rack.data} problems={rack.data.problems}
                         onSelect={(m) => m.asset && navigate(`/assets/${m.asset.uid}`)} />
        )}
      </SectionCard>
    );
  }
  const w = where.data;
  if (!w) return null;
  const span = w.shelf_uid ? "on a shelf" : w.kind === "zero_u" || w.start_u == null ? "0U"
    : w.height_u <= 1 ? `U${w.start_u}` : `U${w.start_u}–U${w.start_u + w.height_u - 1}`;
  return (
    <SectionCard title="In a rack">
      <p className="text-sm text-slate-700">
        <Link to={`/racks/${w.rack.uid}`} className="font-medium text-indigo-600 hover:underline">{w.rack.name}</Link>
        {" · "}{span} · {w.face}
      </p>
    </SectionCard>
  );
}
