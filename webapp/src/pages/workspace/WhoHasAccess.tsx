import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { rolesApi } from "../../api/client";
import type { AccessRoute, PersonAccess, WhoHasAccess as Listing } from "../../api/types";

const RESOURCES: [keyof PersonAccess["rights"], string, number][] = [
  ["objects", "Objects", 4],
  ["tickets", "Tickets", 4],
  ["documents", "Documents", 5],
];

const ROUTE_STYLE: Record<AccessRoute["source"], string> = {
  instance_administrator: "bg-rose-50 text-rose-700 ring-rose-200",
  site_administrator: "bg-amber-50 text-amber-800 ring-amber-200",
  direct: "bg-indigo-50 text-indigo-700 ring-indigo-200",
  group: "bg-sky-50 text-sky-700 ring-sky-200",
  site: "bg-teal-50 text-teal-700 ring-teal-200",
  legacy: "bg-slate-100 text-slate-700 ring-slate-200",
};

function routeText(r: AccessRoute): string {
  switch (r.source) {
    case "instance_administrator": return "Installation administrator";
    case "site_administrator": return `Site administrator of ${r.site ?? "the site"}`;
    case "direct": return r.role ?? r.label;
    case "group": return `${r.role} via ${r.group}`;
    case "site": return `${r.role} site-wide at ${r.site}, via ${r.group}`;
    case "legacy": return "Area permissions";
  }
}

export function RouteChip({ route }: { route: AccessRoute }) {
  return (
    <span className={`inline-block rounded px-1.5 py-0.5 text-xs ring-1 ring-inset ${ROUTE_STYLE[route.source]}`}>
      {routeText(route)}
    </span>
  );
}

/** "Objects: all · Tickets: read" — what a person may do, in a line. */
export function rightsText(rights: PersonAccess["rights"] | Listing["anyone_signed_in"]): string {
  const parts = RESOURCES.flatMap(([key, label, all]) => {
    const actions = (rights as Record<string, string[] | undefined>)[key];
    if (!actions?.length) return [];
    return [`${label}: ${actions.length >= all ? "all" : actions.join(", ")}`];
  });
  return parts.join(" · ") || "—";
}

function Row({ p }: { p: PersonAccess }) {
  const manages = p.rights.workspace?.includes("manage_members");
  return (
    <tr className="border-t border-slate-100 align-top">
      <td className="px-4 py-2">
        <div className="text-slate-900">{p.name || p.email}</div>
        {p.name && <div className="text-xs text-slate-500">{p.email}</div>}
        {!p.signed_in && <div className="text-xs italic text-slate-400">not signed in yet</div>}
        {!p.active && <div className="text-xs italic text-red-500">account deactivated</div>}
      </td>
      <td className="px-4 py-2 text-xs text-slate-600">
        {rightsText(p.rights)}
        {manages && <div className="mt-0.5 font-medium text-slate-800">manages access</div>}
      </td>
      <td className="px-4 py-2">
        <div className="flex flex-wrap gap-1">
          {p.routes.map((r, i) => <RouteChip key={i} route={r} />)}
        </div>
      </td>
    </tr>
  );
}

/** Everyone who can open this workspace, by any route, with what they may do and why. */
export function WhoHasAccess({ workspaceId }: { workspaceId: string }) {
  const [filter, setFilter] = useState("");
  const [showAdmins, setShowAdmins] = useState(false);
  const listing = useQuery({
    queryKey: ["who-has-access", workspaceId],
    queryFn: () => rolesApi.whoHasAccess(workspaceId),
    retry: false,
  });
  if (listing.isLoading) return <p className="mt-6 text-sm text-slate-500">Working out who has access…</p>;
  if (!listing.data) return null;
  const data = listing.data;
  const needle = filter.trim().toLowerCase();
  const matches = (p: PersonAccess) =>
    !needle || p.email.toLowerCase().includes(needle) || (p.name ?? "").toLowerCase().includes(needle);
  const onlyAdmin = (p: PersonAccess) => p.installation_administrator && p.routes.length === 1;
  const own = data.people.filter((p) => !onlyAdmin(p) && matches(p));
  const admins = data.people.filter((p) => onlyAdmin(p) && matches(p));
  const anyone = rightsText(data.anyone_signed_in);

  return (
    <section className="mt-6 rounded-lg border border-slate-200 bg-white" aria-label="Who has access">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
        <div>
          <h2 className="font-medium text-slate-900">Who has access</h2>
          <p className="text-xs text-slate-500">
            {data.counts.people} {data.counts.people === 1 ? "person" : "people"} can open {data.workspace_name}
            {" · "}{data.counts.manage_access} can manage access. Every route counts: roles here, groups,
            site-wide roles, area permissions, administering the site or the installation.
          </p>
        </div>
        {data.people.length > 8 && (
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Find a person…"
            aria-label="Find a person"
            className="w-56 rounded border border-slate-300 px-2 py-1 text-sm"
          />
        )}
      </div>
      <div
        className={`px-4 py-2 text-sm ${data.counts.anyone_signed_in ? "bg-amber-50 text-amber-800" : "text-slate-600"}`}
      >
        {data.counts.anyone_signed_in
          ? <>Anyone signed in to ARGUS, even if not listed: <strong>{anyone}</strong> (set on Area permissions).</>
          : <>Nobody else: someone not listed here cannot open this workspace.</>}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-2 font-medium">Person</th>
              <th className="px-4 py-2 font-medium">Can</th>
              <th className="px-4 py-2 font-medium">Why</th>
            </tr>
          </thead>
          <tbody>
            {own.map((p) => <Row key={p.user_id} p={p} />)}
            {admins.length > 0 && (
              <tr className="border-t border-slate-100">
                <td colSpan={3} className="px-4 py-2 text-sm text-slate-600">
                  <button
                    type="button"
                    onClick={() => setShowAdmins((v) => !v)}
                    className="text-indigo-600 hover:underline"
                  >
                    {showAdmins ? "Hide" : "Show"} {admins.length} installation administrator{admins.length === 1 ? "" : "s"}
                  </button>{" "}
                  — they can do everything in every workspace, with no grant here.
                </td>
              </tr>
            )}
            {showAdmins && admins.map((p) => <Row key={p.user_id} p={p} />)}
          </tbody>
        </table>
      </div>
    </section>
  );
}
