import { TEST_IDS } from "../../test-fixtures/testid-manifest";
import { ActivityIcon, HomeIcon } from "../icons";

type TopbarProps = {
  activePath: string;
};

export function Topbar({ activePath }: TopbarProps) {
  const isInvestigation = activePath.startsWith("/incidents/");
  const incidentId = isInvestigation ? activePath.split("/")[2] : null;
  const incidentPath = isInvestigation ? activePath : null;

  return (
    <header className="sticky top-0 z-30 border-b border-border-subtle bg-bg-base">
      <div className="flex items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <div className="flex min-w-0 items-center gap-2 text-sm">
          <span className="font-semibold text-text-primary">
            {isInvestigation ? "Incident Investigation" : "Operations Overview"}
          </span>
          <span className="hidden text-text-muted sm:inline">/</span>
          <span className="font-data hidden truncate text-text-secondary sm:inline">
            {isInvestigation ? incidentId : "live monitoring"}
          </span>
        </div>

        <span className="hidden items-center gap-2 rounded-md border border-border-subtle bg-surface px-3 py-1.5 text-xs font-medium text-text-secondary sm:flex">
          <span className="h-2 w-2 rounded-full bg-accent-emerald" />
          Live Feed
        </span>
      </div>

      <nav className="flex items-center gap-2 border-t border-border-subtle px-4 py-2 md:hidden">
        <a
          href="/"
          data-testid={TEST_IDS.mobileOverviewLink}
          aria-label="Open operations overview"
          className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium ${
            activePath === "/"
              ? "bg-accent-cyan/10 text-accent-cyan"
              : "text-text-secondary hover:text-text-primary"
          }`}
        >
          <HomeIcon className="h-3.5 w-3.5" /> Overview
        </a>
        {incidentPath ? <a
          href={incidentPath}
          data-testid={TEST_IDS.mobileIncidentLink}
          aria-label="Open current incident investigation"
          className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium ${
            activePath === incidentPath
              ? "bg-accent-purple/10 text-accent-purple"
              : "text-text-secondary hover:text-text-primary"
          }`}
        >
          <ActivityIcon className="h-3.5 w-3.5" /> Incident
        </a> : null}
      </nav>
    </header>
  );
}
