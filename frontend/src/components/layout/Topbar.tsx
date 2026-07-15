import investigationFixture from "../../test-fixtures/golden-investigation-response.json";
import { ActivityIcon, HomeIcon } from "../icons";

type TopbarProps = {
  activePath: string;
};

export function Topbar({ activePath }: TopbarProps) {
  const incidentId = investigationFixture.incident.incident_id;
  const incidentPath = `/incidents/${incidentId}`;
  const isInvestigation = activePath.startsWith("/incidents/");

  return (
    <header className="sticky top-0 z-30 border-b border-border-subtle bg-bg-base/70 backdrop-blur-xl">
      <div className="flex items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <div className="flex min-w-0 items-center gap-2 text-sm">
          <span className="font-semibold text-text-primary">
            {isInvestigation ? "Incident Investigation" : "Operations Overview"}
          </span>
          <span className="hidden text-text-muted sm:inline">/</span>
          <span className="hidden truncate text-text-secondary sm:inline">
            {isInvestigation ? incidentId : "live monitoring"}
          </span>
        </div>

        <span className="hidden items-center gap-2 rounded-full border border-border-subtle bg-surface px-3 py-1.5 text-xs font-medium text-text-secondary sm:flex">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent-emerald opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-accent-emerald" />
          </span>
          Live Feed
        </span>
      </div>

      <nav className="flex items-center gap-2 border-t border-border-subtle px-4 py-2 md:hidden">
        <a
          href="/"
          className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium ${
            activePath === "/"
              ? "bg-accent-cyan/10 text-accent-cyan"
              : "text-text-secondary hover:text-text-primary"
          }`}
        >
          <HomeIcon className="h-3.5 w-3.5" /> Overview
        </a>
        <a
          href={incidentPath}
          className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium ${
            activePath === incidentPath
              ? "bg-accent-purple/10 text-accent-purple"
              : "text-text-secondary hover:text-text-primary"
          }`}
        >
          <ActivityIcon className="h-3.5 w-3.5" /> Incident
        </a>
      </nav>
    </header>
  );
}
