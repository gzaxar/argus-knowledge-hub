import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { ledgerApi, workspacesApi } from "../api/client";
import { signOut } from "../api/signOut";
import { useCurrentWorkspaceId } from "../api/useCurrentWorkspaceId";
import { CommandPalette, useCommandPaletteShortcut } from "../components/hub/CommandPalette";
import { SchemaTree } from "../components/SchemaTree";
import { WorkspaceSwitcher } from "../components/WorkspaceSwitcher";
import { NotificationBell } from "../components/hub/WorkflowPanels";
import { setShowKeys, useShowKeys } from "../api/displayPrefs";

/**
 * One application, three kinds of record. Assets, the service desk and the
 * knowledge base are always one click apart in the sidebar, the search box at
 * the top finds all three at once, and every record links to the other two
 * (see components/hub). The sidebar follows the page: open a ticket and the
 * service-desk links and ticket types are what it shows.
 */
type SectionKey = "assets" | "tickets" | "documents";

interface SectionConfig {
  label: string;
  hint: string;
  icon: string;
  landing: string;
  links: { to: string; label: string; end?: boolean }[];
  treeLabel: string;
  newTypeTo: string;
  newTypeTitle: string;
  appliesTo: "objects" | "tickets" | "documents";
  accent: string;
}

const SECTIONS: Record<SectionKey, SectionConfig> = {
  assets: {
    label: "Assets",
    hint: "Equipment, positions, locations",
    icon: "▣",
    landing: "/assets/search",
    links: [
      { to: "/assets/search", label: "Browse & search" },
      { to: "/map", label: "Map" },
      { to: "/search/advanced?entity=assets", label: "Advanced search (JQL)" },
      { to: "/catalogue/types", label: "Type catalogue" },
      { to: "/labels", label: "Labels & QR codes" },
      { to: "/global-values", label: "Global values" },
      { to: "/bulk-changes", label: "Bulk changes" },
      { to: "/catalogue/equipment-classes", label: "Equipment classes" },
      { to: "/migration/catalogue", label: "Map imported records" },
      { to: "/control-bindings", label: "Channels ↔ hardware" },
    ],
    treeLabel: "Object types",
    newTypeTo: "/schemas/new",
    newTypeTitle: "New object type",
    appliesTo: "objects",
    accent: "bg-indigo-500",
  },
  tickets: {
    label: "Service desk",
    hint: "Incidents, requests, work",
    icon: "◆",
    landing: "/tickets",
    links: [
      { to: "/tickets", label: "All tickets", end: true },
      { to: "/tickets/board", label: "Board" },
      { to: "/tickets/search", label: "Search" },
      { to: "/search/advanced?entity=tickets", label: "Advanced search (JQL)" },
      { to: "/tickets/workflows", label: "Workflows" },
    ],
    treeLabel: "Ticket types",
    newTypeTo: "/schemas/new?applies_to=tickets",
    newTypeTitle: "New ticket type",
    appliesTo: "tickets",
    accent: "bg-amber-500",
  },
  documents: {
    label: "Knowledge base",
    hint: "Procedures, manuals, reports",
    icon: "▤",
    landing: "/documents",
    links: [
      { to: "/documents", label: "All documents", end: true },
      { to: "/search/advanced?entity=documents", label: "Advanced search (JQL)" },
      { to: "/documents/search", label: "Search" },
      { to: "/documents/suggestions", label: "Type suggestions" },
    ],
    treeLabel: "Document types",
    newTypeTo: "/schemas/new?applies_to=documents",
    newTypeTitle: "New document type",
    appliesTo: "documents",
    accent: "bg-emerald-500",
  },
};

const ORDER: SectionKey[] = ["assets", "tickets", "documents"];
const SECTION_KEY = "assetmanagement.activeSection";

function sectionOfPath(pathname: string, search: string): SectionKey | null {
  if (pathname.startsWith("/tickets")) return "tickets";
  if (pathname.startsWith("/documents")) return "documents";
  if (
    pathname.startsWith("/assets") ||
    pathname.startsWith("/labels") ||
    pathname.startsWith("/global-values") ||
    // The tools that work on assets only live in the Assets section.
    pathname.startsWith("/bulk-changes") ||
    pathname.startsWith("/catalogue/") ||
    pathname.startsWith("/migration/catalogue") ||
    pathname.startsWith("/control-bindings")
  )
    return "assets";
  if (pathname.startsWith("/schemas")) {
    if (search.includes("applies_to=tickets")) return "tickets";
    if (search.includes("applies_to=documents")) return "documents";
  }
  return null;
}

function readSection(): SectionKey {
  try {
    const v = localStorage.getItem(SECTION_KEY);
    if (v === "assets" || v === "tickets" || v === "documents") return v;
  } catch {
    // ignore
  }
  return "assets";
}

function NavItem({
  to,
  end,
  children,
  small,
}: {
  to: string;
  end?: boolean;
  children: React.ReactNode;
  small?: boolean;
}) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `flex items-center gap-2 rounded-md px-3 ${small ? "py-1 text-[13px]" : "py-1.5 text-sm"} ${
          isActive ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
        }`
      }
    >
      {children}
    </NavLink>
  );
}

function NewMenu() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [open]);
  const items = [
    { to: "/tickets/new", label: "Ticket", hint: "Report an issue or request work", dot: "bg-amber-500" },
    { to: "/assets/new", label: "Asset", hint: "Register equipment or a position", dot: "bg-indigo-500" },
    { to: "/documents/new", label: "Document", hint: "Procedure, manual, report", dot: "bg-emerald-500" },
    { to: "/beam-model/new", label: "Beam model", hint: "Upload machine models, or write one", dot: "bg-violet-500" },
  ];
  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        + New
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 z-40 mt-1 w-64 overflow-hidden rounded-lg border border-slate-200 bg-white py-1 shadow-lg"
        >
          {items.map((i) => (
            <Link
              key={i.to}
              to={i.to}
              role="menuitem"
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

export function AppShell() {
  const me = useQuery({ queryKey: ["me"], queryFn: workspacesApi.me });
  const navigate = useNavigate();
  const location = useLocation();

  const currentWorkspaceId = useCurrentWorkspaceId();
  const membersLink = currentWorkspaceId ? `/workspaces/${currentWorkspaceId}/members` : null;
  const adminLink = membersLink ?? (me.data?.is_admin ? "/admin/workspaces" : null);

  const [storedSection, setStoredSection] = useState<SectionKey>(readSection);
  const routeSection = sectionOfPath(location.pathname, location.search);
  const activeSection = routeSection ?? storedSection;

  useEffect(() => {
    if (routeSection && routeSection !== storedSection) setStoredSection(routeSection);
  }, [routeSection, storedSection]);
  useEffect(() => {
    try {
      localStorage.setItem(SECTION_KEY, storedSection);
    } catch {
      // ignore
    }
  }, [storedSection]);

  const review = useQuery({ queryKey: ["ledger-review"], queryFn: ledgerApi.review, refetchInterval: 60_000 });
  const reviewCount = review.data
    ? review.data.counts.blocking + review.data.counts.held_revisions + review.data.counts.installation_proposals
    : 0;

  const [paletteOpen, setPaletteOpen] = useState(false);
  const openPalette = useCallback(() => setPaletteOpen(true), []);
  useCommandPaletteShortcut(openPalette);

  const config = SECTIONS[activeSection];
  const accessLink = currentWorkspaceId ? `/workspaces/${currentWorkspaceId}/access` : null;
  const scopedMembersLink = membersLink ? `${membersLink}?section=${activeSection}` : null;
  const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

  return (
    <div className="flex h-screen bg-slate-50">
      <aside className="flex w-64 shrink-0 flex-col border-r border-slate-200 bg-white">
        <Link to="/" className="block border-b border-slate-200 px-4 py-3" title="Operations cockpit">
          <span className="block text-sm font-bold tracking-wide text-slate-900">ARGUS</span>
          <span className="block text-[11px] text-slate-500">Assets · Service · Knowledge</span>
        </Link>
        <WorkspaceSwitcher />

        <nav className="border-t border-slate-200 px-2 py-2" aria-label="Main">
          <NavItem to="/" end>
            <span className="w-4 text-center text-slate-400">⌂</span> Cockpit
          </NavItem>
          <NavItem to="/review">
            <span className="w-4 text-center text-slate-400">✓</span>
            <span className="flex-1">Review queue</span>
            {reviewCount > 0 && (
              <span className="rounded-full bg-red-100 px-1.5 text-[11px] font-medium tabular-nums text-red-700">
                {reviewCount}
              </span>
            )}
          </NavItem>
          {ORDER.map((key) => {
            const s = SECTIONS[key];
            const selected = key === activeSection;
            return (
              <div key={key} className="mt-0.5">
                <button
                  type="button"
                  onClick={() => {
                    setStoredSection(key);
                    navigate(s.landing);
                  }}
                  className={`flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm ${
                    selected ? "font-semibold text-slate-900" : "text-slate-600 hover:bg-slate-100"
                  }`}
                  title={s.hint}
                >
                  <span className={`h-2 w-2 rounded-full ${s.accent}`} aria-hidden />
                  <span className="flex-1">{s.label}</span>
                </button>
                {selected && (
                  <div className="ml-4 mt-0.5 space-y-0.5 border-l border-slate-100 pl-2">
                    {s.links.map((l) => (
                      <NavItem key={l.to} to={l.to} end={l.end} small>
                        {l.label}
                      </NavItem>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
          <div className="mt-2 border-t border-slate-100 pt-2">
            {/* These cross all three kinds of record, so they sit beside the
                sections rather than inside one of them. A tool that works on one
                kind only belongs in that kind's section. */}
            <NavItem to="/graph">
              <span className="w-4 text-center text-slate-400">⌗</span> Knowledge graph
            </NavItem>
            <NavItem to="/beam-model">
              <span className="w-4 text-center text-slate-400">◎</span> Beam model
            </NavItem>
            <NavItem to="/ask">
              <span className="w-4 text-center text-slate-400">?</span> Ask ARGUS
            </NavItem>
            <NavItem to="/help">
              <span className="w-4 text-center text-slate-400">ⓘ</span> Help
            </NavItem>
            <NavItem to="/migration" end>
              <span className="w-4 text-center text-slate-400">⇄</span> Migration to ARGUS
            </NavItem>
          </div>
        </nav>

        {!(
          (config.appliesTo === "objects" && location.pathname === "/assets/search") ||
          (config.appliesTo === "tickets" && location.pathname === "/tickets/search") ||
          (config.appliesTo === "documents" && location.pathname === "/documents/search")
        ) && (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden border-t border-slate-200 px-2 pb-2">
          <div className="flex items-center justify-between px-1.5 pb-1 pt-2">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{config.treeLabel}</p>
            <Link
              to={config.newTypeTo}
              title={config.newTypeTitle}
              className="rounded px-1.5 text-sm font-medium text-slate-400 hover:bg-slate-100 hover:text-slate-700"
            >
              +
            </Link>
          </div>
          <SchemaTree appliesTo={config.appliesTo} />
        </div>
        )}

        <div className="flex flex-wrap items-center gap-1 border-t border-slate-200 px-2 py-1.5 text-xs">
          {accessLink && (
            <NavLink to={accessLink} className="rounded px-2 py-1 text-slate-500 hover:bg-slate-100 hover:text-slate-700">
              Access
            </NavLink>
          )}
          {currentWorkspaceId && (
            <NavLink
              to={`/workspaces/${currentWorkspaceId}/keys`}
              className="rounded px-2 py-1 text-slate-500 hover:bg-slate-100 hover:text-slate-700"
            >
              Keys
            </NavLink>
          )}
          {currentWorkspaceId && (
            <NavLink
              to={`/workspaces/${currentWorkspaceId}/packages`}
              className="rounded px-2 py-1 text-slate-500 hover:bg-slate-100 hover:text-slate-700"
            >
              Packages
            </NavLink>
          )}
          {scopedMembersLink && (
            <NavLink
              to={scopedMembersLink}
              className="rounded px-2 py-1 text-slate-500 hover:bg-slate-100 hover:text-slate-700"
            >
              Members
            </NavLink>
          )}
          {adminLink && (
            <NavLink to={adminLink} className="rounded px-2 py-1 text-slate-500 hover:bg-slate-100 hover:text-slate-700">
              Administration
            </NavLink>
          )}
          <NavLink to="/about" className="rounded px-2 py-1 text-slate-500 hover:bg-slate-100 hover:text-slate-700">
            About
          </NavLink>
          <NavLink to="/account" className="rounded px-2 py-1 text-slate-500 hover:bg-slate-100 hover:text-slate-700">
            My account
          </NavLink>
          <button
            onClick={() => void signOut()}
            className="ml-auto rounded px-2 py-1 text-slate-500 hover:bg-slate-100 hover:text-slate-700"
          >
            Sign out
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-slate-200 bg-white px-6">
          <button
            type="button"
            onClick={openPalette}
            className="flex h-9 w-full max-w-xl items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 text-left text-sm text-slate-400 hover:border-slate-300 hover:bg-white"
            aria-label="Search everything"
          >
            <span aria-hidden>⌕</span>
            <span className="flex-1 truncate">Search assets, tickets and documents…</span>
            <kbd className="rounded border border-slate-200 bg-white px-1.5 text-[10px] text-slate-500">
              {isMac ? "⌘" : "Ctrl"} K
            </kbd>
          </button>
          <div className="ml-auto flex items-center gap-3">
            <ShowKeysToggle />
            <NotificationBell />
            <NewMenu />
            {me.data && (
              <span className="hidden text-xs text-slate-500 md:inline" title={me.data.email ?? undefined}>
                {me.data.name || me.data.email}
              </span>
            )}
          </div>
        </header>
        <main className="flex-1 overflow-auto p-6">
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
