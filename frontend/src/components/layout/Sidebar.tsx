import { useEffect, useState } from "react";
import { TEST_IDS } from "../../test-fixtures/testid-manifest";
import { ChevronLeftIcon, ChevronRightIcon, HomeIcon, ShieldIcon } from "../icons";

type SidebarProps = {
  activePath: string;
};

const COLLAPSE_STORAGE_KEY = "rca-sidebar-collapsed";

export function Sidebar({ activePath }: SidebarProps) {
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    const stored = window.localStorage.getItem(COLLAPSE_STORAGE_KEY);
    if (stored === "true") {
      setCollapsed(true);
    }
  }, []);

  function toggleCollapsed() {
    setCollapsed((current) => {
      const next = !current;
      window.localStorage.setItem(COLLAPSE_STORAGE_KEY, String(next));
      return next;
    });
  }

  const incidentPath = activePath.startsWith("/incidents/") ? activePath : null;

  return (
    <aside
      className={`sticky top-0 hidden h-screen shrink-0 flex-col border-r border-border-subtle bg-surface-strong backdrop-blur-xl transition-[width] duration-300 md:flex ${
        collapsed ? "w-20" : "w-64"
      }`}
    >
      <div className="flex items-center gap-3 border-b border-border-subtle px-5 py-6">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-accent-cyan-strong to-accent-purple-strong text-slate-950">
          <ShieldIcon className="h-5 w-5" />
        </span>
        {!collapsed ? (
          <div className="min-w-0">
            <p className="truncate text-sm font-bold text-text-primary">Network RCA</p>
            <p className="truncate text-xs text-text-secondary">SOC Console</p>
          </div>
        ) : null}
      </div>

      <nav className="flex-1 space-y-1 px-3 py-4">
        <a
          href="/"
          data-testid={TEST_IDS.sidebarOverviewLink}
          aria-label="Open operations overview"
          className={`flex items-center gap-3 rounded-2xl px-3 py-2.5 text-sm font-medium transition-colors ${
            activePath === "/"
              ? "bg-accent-cyan/10 text-accent-cyan"
              : "text-text-secondary hover:bg-white/5 hover:text-text-primary"
          }`}
        >
          <HomeIcon className="h-4 w-4 shrink-0" />
          {!collapsed ? <span>Overview</span> : null}
        </a>

        {!collapsed ? (
          <p className="px-3 pb-1 pt-4 text-[0.65rem] font-semibold uppercase tracking-widest text-text-muted">
            Active Incidents
          </p>
        ) : null}
        {incidentPath ? <a
          href={incidentPath}
          data-testid={TEST_IDS.sidebarIncidentLink}
          aria-label="Open current incident investigation"
          className={`flex items-center gap-3 rounded-2xl px-3 py-2.5 text-sm font-medium transition-colors ${
            activePath === incidentPath
              ? "bg-accent-purple/10 text-accent-purple"
              : "text-text-secondary hover:bg-white/5 hover:text-text-primary"
          }`}
        >
          <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-accent-red" />
          {!collapsed ? <span className="truncate">Current incident</span> : null}
        </a> : null}
      </nav>

      <button
        type="button"
        data-testid={TEST_IDS.sidebarToggle}
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        onClick={toggleCollapsed}
        className="m-3 flex items-center justify-center gap-2 rounded-2xl border border-border-subtle py-2 text-text-secondary transition-colors hover:border-accent-cyan/40 hover:text-accent-cyan"
      >
        {collapsed ? (
          <ChevronRightIcon className="h-4 w-4" />
        ) : (
          <ChevronLeftIcon className="h-4 w-4" />
        )}
      </button>
    </aside>
  );
}
