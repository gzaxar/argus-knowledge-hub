import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { workspacesApi } from "../../api/client";
import { signOut } from "../../api/signOut";
import type { PortalStatus } from "../../api/portalTypes";

/** A site's portal: a help-centre band with the site's name, the way back to its services, and the person's own
 *  requests always one click away. The emergency text is shown as configured, never from a model's answer. */
export function PortalFrame({ siteId, siteName, crumbs = [], emergency, children, hero }: {
  siteId?: string;
  siteName?: string;
  crumbs?: { to?: string; label: string }[];
  emergency?: string | null;
  hero?: ReactNode;
  children: ReactNode;
}) {
  const home = siteId ? `/support/${siteId}` : "/support";
  return (
    <div className="flex min-h-screen flex-col bg-slate-50">
      <a href="#portal-main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2 focus:text-sm">
        Skip to content
      </a>
      <header className="bg-gradient-to-r from-slate-900 via-slate-800 to-indigo-900 text-white">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 sm:px-6">
          <Link to={home} className="flex min-w-0 items-center gap-2 font-semibold">
            <span aria-hidden className="flex h-7 w-7 items-center justify-center rounded bg-white/15 text-sm">A</span>
            <span className="truncate">{siteName ? `${siteName} · Help centre` : "ARGUS Help centre"}</span>
          </Link>
          <nav aria-label="Service portal" className="ml-auto flex items-center gap-1 text-sm">
            {siteId && <Link to={home} className="rounded px-3 py-1.5 hover:bg-white/10">Services</Link>}
            {siteId && (
              <Link to={`/support/${siteId}/requests`}
                    className="rounded bg-white px-3 py-1.5 font-medium text-slate-900 hover:bg-slate-100">
                My requests
              </Link>
            )}
            <AccountMenu />
          </nav>
        </div>
        {hero && <div className="mx-auto max-w-5xl px-4 pb-10 pt-6 sm:px-6">{hero}</div>}
      </header>
      {emergency && (
        <div role="note" className="border-b border-red-200 bg-red-50">
          <p className="mx-auto max-w-5xl px-4 py-2 text-sm text-red-800 sm:px-6">
            <span className="font-semibold">Emergency?</span> {emergency}
          </p>
        </div>
      )}
      <main id="portal-main" className="mx-auto w-full max-w-5xl flex-1 px-4 py-6 sm:px-6">
        {crumbs.length > 0 && (
          <nav aria-label="Breadcrumb" className="mb-4 text-sm text-slate-500">
            <ol className="flex flex-wrap items-center gap-1">
              {crumbs.map((c, i) => (
                <li key={i} className="flex items-center gap-1">
                  {i > 0 && <span aria-hidden>/</span>}
                  {c.to ? <Link to={c.to} className="hover:text-slate-800 hover:underline">{c.label}</Link>
                    : <span aria-current="page" className="text-slate-700">{c.label}</span>}
                </li>
              ))}
            </ol>
          </nav>
        )}
        {children}
      </main>
      <footer className="border-t border-slate-200 bg-white">
        <p className="mx-auto max-w-5xl px-4 py-3 text-xs text-slate-400 sm:px-6">ARGUS Knowledge Hub · Help centre</p>
      </footer>
    </div>
  );
}

/** Who is signed in, the way back to ARGUS for someone with a workspace to work in, and signing out. */
function AccountMenu() {
  const me = useQuery({ queryKey: ["me"], queryFn: workspacesApi.me, staleTime: 300_000, retry: false });
  const mine = useQuery({ queryKey: ["my-workspaces"], queryFn: workspacesApi.listMine, staleTime: 300_000, retry: false });
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", esc);
    return () => { window.removeEventListener("mousedown", close); window.removeEventListener("keydown", esc); };
  }, [open]);
  const name = me.data?.name || me.data?.email || "Account";
  const works = (mine.data?.length ?? 0) > 0;
  return (
    <div className="relative" ref={ref}>
      <button type="button" aria-expanded={open} aria-haspopup="menu" onClick={() => setOpen((v) => !v)}
              className="flex items-center gap-2 rounded px-2 py-1.5 hover:bg-white/10">
        <span aria-hidden className="flex h-7 w-7 items-center justify-center rounded-full bg-white/20 text-xs font-semibold">
          {name.slice(0, 1).toUpperCase()}
        </span>
        <span className="sr-only">Account: {name}</span>
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-40 mt-1 w-56 overflow-hidden rounded-lg border border-slate-200 bg-white py-1 text-sm text-slate-700 shadow-lg">
          <p className="truncate px-3 py-2 text-xs text-slate-500">{name}</p>
          {works && <Link role="menuitem" to="/" className="block px-3 py-2 hover:bg-slate-50">Open ARGUS</Link>}
          <Link role="menuitem" to="/support" className="block px-3 py-2 hover:bg-slate-50">All help centres</Link>
          <button role="menuitem" type="button" onClick={() => signOut()} className="block w-full px-3 py-2 text-left hover:bg-slate-50">
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

const LOZENGE: Record<string, string> = {
  open: "bg-slate-200 text-slate-800",
  active: "bg-sky-100 text-sky-800",
  waiting: "bg-amber-100 text-amber-900",
  done: "bg-emerald-100 text-emerald-800",
};

export function StatusLozenge({ status }: { status: PortalStatus }) {
  return (
    <span className={`inline-block rounded px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${
      LOZENGE[status.category] ?? LOZENGE.open}`}>
      {status.label}
    </span>
  );
}

export function PortalMessage({ tone = "info", children }: { tone?: "info" | "error" | "ok"; children: ReactNode }) {
  const cls = tone === "error" ? "border-red-200 bg-red-50 text-red-800"
    : tone === "ok" ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-slate-200 bg-white text-slate-700";
  return <div role={tone === "error" ? "alert" : "status"} className={`rounded-lg border px-4 py-3 text-sm ${cls}`}>
    {children}</div>;
}

export const when = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString() : "");
