import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { sitesApi, workspacesApi } from "../../api/client";
import { AccessChanges, SiteAdministrators, SiteWideGroupAccess } from "../workspace/Access";

/** A site's own administration: who administers it, the roles its groups have at every facility at it, and the
 *  facilities those reach. For an administrator of the site or of the installation. */
function useSiteName(siteId: string) {
  const me = useQuery({ queryKey: ["me"], queryFn: workspacesApi.me });
  const mine = useQuery({ queryKey: ["my-workspaces"], queryFn: workspacesApi.listMine });
  return me.data?.administered_sites?.find((s) => s.id === siteId)?.name
    ?? mine.data?.find((w) => w.id === siteId)?.name ?? siteId;
}

function Heading({ siteId, title, children }: { siteId: string; title: string; children: ReactNode }) {
  const name = useSiteName(siteId);
  return (
    <div>
      <h1 className="text-2xl font-semibold text-slate-900">
        {title} <span className="text-base font-normal text-slate-500">· site {name}</span>
      </h1>
      <p className="mt-1 max-w-3xl text-sm text-slate-500">{children}</p>
    </div>
  );
}

export function SiteAdministratorsPage() {
  const { siteId = "" } = useParams();
  return (
    <div className="max-w-4xl">
      <Heading siteId={siteId} title="Administrators">
        A site administrator manages access to this site and to every facility currently at it: they grant roles,
        give the site's groups site-wide access and name other site administrators. A facility that moves to
        another site leaves their authority with it.
      </Heading>
      <SiteAdministrators siteId={siteId} heading={false} />
    </div>
  );
}

export function SiteGroupAccessPage() {
  const { siteId = "" } = useParams();
  return (
    <div className="max-w-4xl">
      <Heading siteId={siteId} title="Site-wide group access">
        A role given to a group here holds at every facility currently at the site, and at each one that joins it
        later. Each facility lists it under <i>Inherited from the site</i> on its Access page.
      </Heading>
      <SiteWideGroupAccess siteId={siteId} heading={false} />
      <AccessChanges workspaceId={siteId} />
    </div>
  );
}

export function SiteFacilitiesPage() {
  const { siteId = "" } = useParams();
  const data = useQuery({ queryKey: ["site-group-grants", siteId], queryFn: () => sitesApi.groupGrants(siteId), retry: false });
  const mine = useQuery({ queryKey: ["my-workspaces"], queryFn: workspacesApi.listMine });
  const name = (id: string) => mine.data?.find((w) => w.id === id)?.name ?? id;
  const facilities = (data.data?.workspaces ?? []).filter((id) => id !== siteId);
  return (
    <div className="max-w-4xl">
      <Heading siteId={siteId} title="Facilities">
        The workspaces at this site now. Site-wide access and the site administrators' authority reach each of
        them. Moving a facility to another site is done by an installation administrator, under{" "}
        <i>Installation › Workspaces</i>, which first shows who would gain or lose access.
      </Heading>
      {data.isError && <p className="mt-4 text-sm text-red-600">Only an administrator of this site or of the installation can see its facilities.</p>}
      {data.isSuccess && facilities.length === 0 && <p className="mt-4 text-sm text-slate-500">No facility is at this site yet.</p>}
      {facilities.length > 0 && (
        <ul className="mt-4 divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white text-sm">
          {facilities.map((id) => (
            <li key={id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2">
              <span>{name(id)} <code className="text-xs text-slate-500">{id}</code></span>
              <span className="flex gap-3 text-xs">
                <Link to={`/workspaces/${id}/access`} className="text-indigo-600 hover:underline">Access</Link>
                <Link to={`/workspaces/${id}/members`} className="text-indigo-600 hover:underline">Area permissions</Link>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
