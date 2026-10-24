import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { ledgerApi, workspacesApi } from "../api/client";
import { signOut } from "../api/signOut";
import { useCurrentWorkspaceId } from "../api/useCurrentWorkspaceId";
import { CommandPalette, useCommandPaletteShortcut } from "../components/hub/CommandPalette";
import { DemoStrip } from "../components/demo/DemoTour";
import { WorkspaceSwitcher } from "../components/WorkspaceSwitcher";
import { NotificationBell } from "../components/hub/WorkflowPanels";
import { setShowKeys, useShowKeys } from "../api/displayPrefs";
import { has, useCapabilities } from "../api/useCapabilities";
import type { WorkspaceCapabilities } from "../api/client";

/**
 * One application, three kinds of record, one stable sidebar: the major areas, always in the same place. What
 * belongs to one area (its types, its tools) is on that area's pages — the type explorer beside the results, a
 * Tools menu in the page header — and configuration is under Workspace settings. On a narrow screen the
 * sidebar is a drawer opened from the header.
 */
interface Area {
  to: string;
  label: string;
  icon: string;
  /** Other addresses that belong to this area, so it stays marked as current there. */
  also?: (path: string, search: string) => boolean;
  needs?: keyof WorkspaceCapabilities["features"];
  badge?: number;
  end?: boolean;
}

export function areas(features: WorkspaceCapabilities["features"] | null, reviewCount: number): Area[] {
  const equipment = has(features, "equipment");
  const all: Area[] = [
    { to: "/", label: "Cockpit", icon: "⌂", end: true },
    {
      to: "/assets/search", label: equipment ? "Assets" : "Records", icon: "▣",
      also: (p, s) => /^\/(assets|labels|bulk-changes|migration\/catalogue|control-bindings|catalogue)/.test(p) ||
        (p.startsWith("/search/advanced") && s.includes("entity=assets")) ||
        (p.startsWith("/schemas") && !/applies_to=(tickets|documents)/.test(s)),
    },
    {
      to: "/tickets", label: "Tickets", icon: "◆",
      also: (p, s) => p.startsWith("/tickets") || (p.startsWith("/search/advanced") && s.includes("entity=tickets")) ||
        (p.startsWith("/schemas") && s.includes("applies_to=tickets")),
    },
    {
      to: "/documents", label: "Documents", icon: "▤",
      also: (p, s) => p.startsWith("/documents") || (p.startsWith("/search/advanced") && s.includes("entity=documents")) ||
        (p.startsWith("/schemas") && s.includes("applies_to=documents")),
    },
    { to: "/activities", label: "Activities", icon: "↻" },
    { to: "/map", label: "Map", icon: "⌖", needs: "map" },
    { to: "/graph", label: "Knowledge graph", icon: "⌗" },
    { to: "/beam-model", label: "Beam model", icon: "◎", needs: "beam_model", also: (p) => p.startsWith("/beam-model") },
    { to: "/ask", label: "Ask ARGUS", icon: "?" },
    { to: "/review", label: "Review queue", icon: "✓", badge: reviewCount },
  ];
  return all.filter((a) => !a.needs || has(features, a.needs));
}

export function SideNav({ items, onNavigate }: { items: Area[]; onNavigate?: () => void }) {
  const location = useLocation();
  return (
    <nav aria-label="Main" className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
      <ul className="space-y-0.5">
        {items.map((a) => {
          const own = a.end ? location.pathname === a.to : location.pathname.startsWith(a.to);
          const current = own || !!a.also?.(location.pathname, location.search);
          return (
            <li key={a.to}>
              <Link
                to={a.to}
                onClick={onNavigate}
                aria-current={current ? "page" : undefined}
                className={`flex items-center gap-2 rounded-md px-3 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 ${
                  current ? "bg-slate-900 font-medium text-white" : "text-slate-700 hover:bg-slate-100 hover:text-slate-900"
                }`}
              >
                <span aria-hidden className={`w-4 text-center ${current ? "text-slate-300" : "text-slate-400"}`}>{a.icon}</span>
                <span className="min-w-0 flex-1 truncate">{a.label}</span>
                {!!a.badge && a.badge > 0 && (
                  <span className="rounded-full bg-red-100 px-1.5 text-[11px] font-medium tabular-nums text-red-800"
                        aria-label={`${a.badge} waiting`}>
                    {a.badge}
                  </span>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function NewMenu() {
  const features = useCapabilities();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", esc);
    return () => { window.removeEventListener("mousedown", close); window.removeEventListener("keydown", esc); };
  }, [open]);
  const equipment = has(features, "equipment");
  const items = [
    { to: "/tickets/new", label: "Ticket", hint: "Report an issue or request work", dot: "bg-amber-500" },
    equipment
      ? { to: "/assets/new", label: "Asset", hint: "Register equipment or a position", dot: "bg-indigo-500" }
      : { to: "/assets/new", label: "Record", hint: "An agreement, a party, a case", dot: "bg-indigo-500" },
    { to: "/documents/new", label: "Document", hint: "Procedure, manual, report", dot: "bg-emerald-500" },
    ...(has(features, "beam_model")
      ? [{ to: "/beam-model/new", label: "Beam model", hint: "Upload machine models, or write one", dot: "bg-violet-500" }]
      : []),
  ];
  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800"
        aria-expanded={open}
      >
        + New
      </button>
      {open && (
        <div
          className="absolute right-0 z-40 mt-1 w-64 overflow-hidden rounded-lg border border-slate-200 bg-white py-1 shadow-lg"
        >
          {items.map((i) => (
            <Link
              key={i.to}
              to={i.to}
             
              onClick={() => setOpen(false)}
              className="flex items-start gap-3 px-3 py-2 hover:bg-slate-50"
            >
              <span className={`mt-1.5 h-2 w-2 rounded-full ${i.dot}`} />
              <span>
                <span className="block text-sm font-medium text-slate-900">{i.label}</span>
                <span className="block text-xs text-slate-500">{i.hint}</span>
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

/** A menu in the header: a button and the links it opens. */
function HeaderMenu({
  label,
  title,
  items,
  align = "right",
}: {
  label: React.ReactNode;
  title: string;
  items: ({ to: string; label: string; hint?: string } | { action: () => void; label: string; hint?: string })[];
  align?: "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", esc);
    return () => { window.removeEventListener("mousedown", close); window.removeEventListener("keydown", esc); };
  }, [open]);
  if (items.length === 0) return null;
  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title={title}
        aria-expanded={open}
        className="flex items-center gap-1 rounded-md px-2 py-1.5 text-sm text-slate-600 hover:bg-slate-100 hover:text-slate-900"
      >
        {label}
      </button>
      {open && (
        <div
          className={`absolute z-40 mt-1 w-60 overflow-hidden rounded-lg border border-slate-200 bg-white py-1 shadow-lg ${
            align === "right" ? "right-0" : "left-0"
          }`}
        >
          {items.map((i) =>
            "to" in i ? (
              <Link
                key={i.label}
                to={i.to}
               
                onClick={() => setOpen(false)}
                className="block px-3 py-1.5 hover:bg-slate-50"
              >
                <span className="block text-sm text-slate-800">{i.label}</span>
                {i.hint && <span className="block text-xs text-slate-500">{i.hint}</span>}
              </Link>
            ) : (
              <button
                key={i.label}
                type="button"
               
                onClick={() => {
                  setOpen(false);
                  i.action();
                }}
                className="block w-full px-3 py-1.5 text-left text-sm text-slate-800 hover:bg-slate-50"
              >
                {i.label}
              </button>
            ),
          )}
        </div>
      )}
    </div>
  );
}

export function AppShell() {
  const me = useQuery({ queryKey: ["me"], queryFn: workspacesApi.me });
  const location = useLocation();
  const currentWorkspaceId = useCurrentWorkspaceId();
  const membersLink = currentWorkspaceId ? `/workspaces/${currentWorkspaceId}/members` : null;
  const adminLink = membersLink ?? (me.data?.is_admin ? "/admin/workspaces" : null);

  const review = useQuery({ queryKey: ["ledger-review"], queryFn: ledgerApi.review, refetchInterval: 60_000 });
  const reviewCount = review.data
    ? review.data.counts.blocking + review.data.counts.held_revisions + review.data.counts.installation_proposals
    : 0;

  const [paletteOpen, setPaletteOpen] = useState(false);
  const openPalette = useCallback(() => setPaletteOpen(true), []);
  useCommandPaletteShortcut(openPalette);

  // The drawer of a narrow screen: closed by a choice, by Escape, or by moving to another page.
  const [drawer, setDrawer] = useState(false);
  const drawerRef = useRef<HTMLDivElement>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  useEffect(() => setDrawer(false), [location.pathname]);
  useEffect(() => {
    if (!drawer) return;
    drawerRef.current?.querySelector<HTMLElement>("a, button")?.focus();
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setDrawer(false); menuButton.current?.focus(); }
    };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [drawer]);

  const features = useCapabilities();
  const items = areas(features, reviewCount);
  const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

  const settingsItems = currentWorkspaceId
    ? [
        { to: `/workspaces/${currentWorkspaceId}/access`, label: "Access", hint: "Who may see and change what" },
        { to: `/workspaces/${currentWorkspaceId}/members`, label: "Members" },
        { to: `/workspaces/${currentWorkspaceId}/packages`, label: "Packages", hint: "Types, kinds and workflows" },
        { to: "/catalogue/types", label: "Type catalogue", hint: "Object, ticket and document types" },
        { to: "/global-values", label: "Global values", hint: "Shared lists: states, priorities…" },
        { to: "/tickets/workflows", label: "Ticket workflows" },
        ...(has(features, "equipment") ? [{ to: "/catalogue/equipment-classes", label: "Equipment classes" }] : []),
        { to: `/workspaces/${currentWorkspaceId}/keys`, label: "Keys", hint: "How records are numbered" },
        ...(adminLink ? [{ to: adminLink, label: "Administration", hint: "Imports, integrations, AI, tokens" }] : []),
      ]
    : adminLink
      ? [{ to: adminLink, label: "Administration" }]
      : [];
  const accountItems = [
    { to: "/account", label: "My account" },
    { to: "/about", label: "About ARGUS" },
    { action: () => void signOut(), label: "Sign out" },
  ];

  const brand = (
    <Link to="/" className="flex min-w-0 items-baseline gap-2 px-4 py-2.5" title="Operations cockpit">
      <span className="text-sm font-bold tracking-wide text-slate-900">ARGUS</span>
      <span className="truncate text-sm text-slate-600">Knowledge Hub</span>
    </Link>
  );

  return (
    <div className="flex h-screen bg-slate-50">
      <aside className="hidden w-56 shrink-0 flex-col border-r border-slate-200 bg-white lg:flex">
        <div className="border-b border-slate-200">{brand}</div>
        <WorkspaceSwitcher />
        <SideNav items={items} />
      </aside>

      {drawer && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-slate-900/40" aria-hidden onClick={() => setDrawer(false)} />
          <div ref={drawerRef} id="main-drawer" role="dialog" aria-modal="true" aria-label="Navigation"
               className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-slate-200 pr-2">
              {brand}
              <button type="button" onClick={() => setDrawer(false)} aria-label="Close navigation"
                      className="rounded px-2 py-1 text-lg text-slate-500 hover:bg-slate-100">×</button>
            </div>
            <WorkspaceSwitcher />
            <SideNav items={items} onNavigate={() => setDrawer(false)} />
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-slate-200 bg-white px-3 sm:px-4 lg:px-6">
          <button ref={menuButton} type="button" onClick={() => setDrawer(true)} aria-label="Open navigation"
                  aria-expanded={drawer} aria-controls="main-drawer"
                  className="rounded-md px-2 py-1.5 text-lg text-slate-700 hover:bg-slate-100 lg:hidden">
            ☰
          </button>
          <button
            type="button"
            onClick={openPalette}
            className="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 text-left text-sm text-slate-500 hover:border-slate-300 hover:bg-white sm:max-w-xl"
            aria-label="Search everything"
          >
            <span aria-hidden>⌕</span>
            <span className="flex-1 truncate">Search assets, tickets and documents…</span>
            <kbd className="hidden rounded border border-slate-200 bg-white px-1.5 text-[10px] text-slate-500 sm:inline">
              {isMac ? "⌘" : "Ctrl"} K
            </kbd>
          </button>
          <div className="ml-auto flex shrink-0 items-center gap-1">
            <ShowKeysToggle />
            <NotificationBell />
            <Link
              to="/help"
              title="Help"
              aria-label="Help"
              className="hidden rounded-md px-2 py-1.5 text-sm text-slate-600 hover:bg-slate-100 hover:text-slate-900 sm:block"
            >
              ⓘ <span className="hidden xl:inline">Help</span>
            </Link>
            <HeaderMenu
              label={
                <>
                  <span aria-hidden>⚙</span> <span className="hidden xl:inline">Workspace settings</span>
                  <span className="sr-only xl:hidden">Workspace settings</span>
                </>
              }
              title="This workspace's settings and administration"
              items={settingsItems}
            />
            <NewMenu />
            <HeaderMenu
              label={
                <span className="flex max-w-[10rem] items-center gap-1 text-xs" title={me.data?.email ?? undefined}>
                  <span className="hidden truncate md:inline">{me.data ? me.data.name || me.data.email : "Account"}</span>
                  <span className="md:hidden" aria-hidden>👤</span>
                  <span className="sr-only md:hidden">Account</span>
                  <span aria-hidden>▾</span>
                </span>
              }
              title="Your account"
              items={accountItems}
            />
          </div>
        </header>
        <main className="flex-1 overflow-auto p-3 sm:p-4 lg:p-6">
          <div className="-mx-3 -mt-3 mb-3 sm:-mx-4 sm:-mt-4 sm:mb-4 lg:-mx-6 lg:-mt-6 lg:mb-6"><DemoStrip /></div>
          <Outlet />
        </main>
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}


/** Show records with their key (SPARC-IP-01 · Ion pump) or by name and title only; kept in this browser. */
function ShowKeysToggle() {
  const show = useShowKeys();
  return (
    <label className="hidden cursor-pointer items-center gap-1 text-xs text-slate-500 md:flex"
           title="Show keys and codes beside names and titles, in lists and on record pages">
      <input type="checkbox" checked={show} onChange={(e) => setShowKeys(e.target.checked)} />
      Show keys
    </label>
  );
}
