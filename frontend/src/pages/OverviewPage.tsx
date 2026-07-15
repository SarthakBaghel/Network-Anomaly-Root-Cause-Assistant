import { useEffect, useMemo, useState } from "react";

import type { components } from "../contracts/openapi";
import { apiClient } from "../api/client";
import investigationFixture from "../test-fixtures/golden-investigation-response.json";
import {
  TEST_IDS,
  incidentRowTestId,
  sourceHealthTestId,
} from "../test-fixtures/testid-manifest";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { StatCard } from "../components/ui/StatCard";
import {
  ActivityIcon,
  AlertTriangleIcon,
  BellIcon,
  ClockIcon,
  DatabaseIcon,
  FileTextIcon,
  GaugeIcon,
  NetworkIcon,
  RadioIcon,
  SettingsIcon,
} from "../components/icons";

type InvestigationResponse = components["schemas"]["InvestigationResponse"];

type SourceHealth = {
  id: string;
  title: string;
  source: string;
  status: "ready" | "error";
  ingestAt: string;
  accepted: number;
  collapsed: number;
  quarantined: number;
};

type AnomalyRecord = {
  anomalyId: string;
  entity: string;
  type: string;
  score: number;
  detectorId: string;
  timestamp: string;
};

const initialHealth: SourceHealth[] = [
  {
    id: "simulator.prometheus",
    title: "simulator.prometheus",
    source: "metrics",
    status: "ready",
    ingestAt: "2026-07-14T09:30:30Z",
    accepted: 7_800,
    collapsed: 0,
    quarantined: 0,
  },
  {
    id: "simulator.syslog",
    title: "simulator.syslog",
    source: "logs",
    status: "ready",
    ingestAt: "2026-07-14T09:29:58Z",
    accepted: 530,
    collapsed: 3,
    quarantined: 0,
  },
  {
    id: "simulator.alertmanager",
    title: "simulator.alertmanager",
    source: "alerts",
    status: "ready",
    ingestAt: "2026-07-14T09:30:05Z",
    accepted: 4,
    collapsed: 0,
    quarantined: 0,
  },
  {
    id: "simulator.config_audit",
    title: "simulator.config_audit",
    source: "config changes",
    status: "ready",
    ingestAt: "2026-07-14T09:30:00Z",
    accepted: 1,
    collapsed: 0,
    quarantined: 0,
  },
  {
    id: "fixture.cmdb_topology",
    title: "fixture.cmdb_topology",
    source: "topology fixture",
    status: "ready",
    ingestAt: "2026-07-14T09:28:30Z",
    accepted: 1,
    collapsed: 0,
    quarantined: 0,
  },
];

const scenarios = [
  { id: "gateway_rate_limit_disabled", title: "Gateway rate-limit disabled" },
  { id: "golden_scenario", title: "Golden scenario" },
];

const baseAnomalies: AnomalyRecord[] = [
  {
    anomalyId: "anom_001",
    entity: "api-gateway-01",
    type: "metric spike",
    score: 94.2,
    detectorId: "detector_prometheus_01",
    timestamp: "2026-07-14T09:30:30Z",
  },
  {
    anomalyId: "anom_002",
    entity: "auth-service-01",
    type: "log error burst",
    score: 87.3,
    detectorId: "detector_syslog_03",
    timestamp: "2026-07-14T09:31:10Z",
  },
  {
    anomalyId: "anom_003",
    entity: "api-gateway-01",
    type: "alert flood",
    score: 91.8,
    detectorId: "detector_alertmanager_02",
    timestamp: "2026-07-14T09:31:35Z",
  },
];

const SOURCE_ICON: Record<string, typeof ActivityIcon> = {
  "simulator.prometheus": ActivityIcon,
  "simulator.syslog": FileTextIcon,
  "simulator.alertmanager": BellIcon,
  "simulator.config_audit": SettingsIcon,
  "fixture.cmdb_topology": NetworkIcon,
};

function formatClock(date: Date) {
  return date.toLocaleTimeString("en-US", { hour12: false });
}

function formatDate(timestamp: string) {
  return new Date(timestamp).toLocaleString("en-US", {
    hour12: false,
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function severityBadgeVariant(severity: "low" | "medium" | "high" | "critical") {
  switch (severity) {
    case "low":
      return "success" as const;
    case "medium":
      return "warning" as const;
    case "high":
      return "warning" as const;
    case "critical":
      return "danger" as const;
  }
}

export function OverviewPage() {
  const [health, setHealth] = useState<SourceHealth[]>(initialHealth);
  const [preferredScenario, setPreferredScenario] = useState(scenarios[0].id);
  const [transitioning, setTransitioning] = useState(false);
  const [clock, setClock] = useState(() => new Date());
  const [anomalies, setAnomalies] = useState<AnomalyRecord[]>(baseAnomalies);
  const [statusMessage, setStatusMessage] = useState("Scenario not triggered");
  const [scenarioTriggered, setScenarioTriggered] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);

  const investigation =
    investigationFixture as unknown as InvestigationResponse;

  const incidentRow = useMemo(() => {
    const candidateEntities = Array.from(
      new Set(
        investigation.hypotheses.map(
          (hypothesis) => hypothesis.candidate_entity_id,
        ),
      ),
    );
    return {
      incidentId: investigation.incident.incident_id,
      title: investigation.incident.title,
      severity: "high" as const,
      affectedEntities: candidateEntities,
      startTime: investigation.analysis_run.created_at,
      status: investigation.incident.status,
    };
  }, [investigation]);

  useEffect(() => {
    const tick = window.setInterval(() => setClock(new Date()), 1_000);
    return () => window.clearInterval(tick);
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setAnomalies((current) => [
        ...current.slice(0, 19),
        {
          anomalyId: `anom_${Math.floor(Math.random() * 1_000_000)}`,
          entity: "api-gateway-01",
          type: "metric spike",
          score: Number((80 + Math.random() * 20).toFixed(1)),
          detectorId: "detector_prometheus_01",
          timestamp: new Date().toISOString(),
        },
      ]);
    }, 10_000);

    return () => window.clearInterval(timer);
  }, []);

  async function triggerScenario(scenarioId: string) {
    setTransitioning(true);
    setApiError(null);
    setStatusMessage("Triggering scenario...");
    try {
      await apiClient.post(`/simulator/scenarios/${scenarioId}/trigger`);
      setPreferredScenario(scenarioId);
      setScenarioTriggered(true);
      setStatusMessage("Scenario triggered");
    } catch (error: any) {
      const code = error?.response?.data?.code as string | undefined;
      setApiError(
        code
          ? `${code}: Unable to trigger scenario`
          : "Unable to trigger scenario",
      );
      setStatusMessage("Scenario trigger failed");
    } finally {
      setTransitioning(false);
    }
  }

  async function handleSimulatorAction(action: "start" | "stop" | "reset") {
    setTransitioning(true);
    setApiError(null);
    setStatusMessage(
      `${action.charAt(0).toUpperCase() + action.slice(1)}ing simulator...`,
    );
    try {
      await apiClient.post(`/simulator/${action}`);
      setStatusMessage(`Simulator ${action}ed`);
    } catch (error: any) {
      const code = error?.response?.data?.code as string | undefined;
      setApiError(
        code
          ? `${code}: Simulator ${action} failed`
          : `Simulator ${action} failed`,
      );
      setStatusMessage(`Simulator ${action} failed`);
    } finally {
      setTransitioning(false);
    }
  }

  const hasQuarantine = health.some((source) => source.quarantined > 0);

  const totalAccepted = useMemo(
    () => health.reduce((sum, source) => sum + source.accepted, 0),
    [health],
  );
  const totalQuarantined = useMemo(
    () => health.reduce((sum, source) => sum + source.quarantined, 0),
    [health],
  );
  const sourcesOnline = useMemo(
    () => health.filter((source) => source.status === "ready").length,
    [health],
  );

  return (
    <main className="mx-auto max-w-6xl space-y-8 p-4 sm:p-6 lg:p-8">
      <header className="animate-fade-in-up">
        <p className="text-xs font-bold uppercase tracking-[0.3em] text-accent-cyan">
          Operations
        </p>
        <h1 className="mt-2 text-3xl font-extrabold tracking-tight text-text-primary sm:text-4xl">
          Network Anomaly RCA
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-text-secondary sm:text-base">
          Phase 1 overview with source health, simulator controls, anomalies,
          and incident navigation.
        </p>
      </header>

      {apiError ? (
        <div
          role="alert"
          className="glass-panel animate-fade-in-up flex items-center gap-3 border-accent-red/30 bg-accent-red/10 px-4 py-3 text-sm text-accent-red"
        >
          <AlertTriangleIcon className="h-4 w-4 shrink-0" />
          <span>
            <strong className="font-semibold">Error:</strong> {apiError}
          </span>
        </div>
      ) : null}

      {hasQuarantine ? (
        <div
          role="status"
          className="glass-panel animate-fade-in-up flex items-center gap-3 border-accent-amber/30 bg-accent-amber/10 px-4 py-3 text-sm text-accent-amber"
        >
          <AlertTriangleIcon className="h-4 w-4 shrink-0" />
          Quarantine warning: at least one source has quarantined records.
        </div>
      ) : null}

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Events Accepted"
          value={totalAccepted}
          icon={<GaugeIcon className="h-5 w-5" />}
          accent="cyan"
        />
        <StatCard
          label="Anomalies Detected"
          value={anomalies.length}
          icon={<ActivityIcon className="h-5 w-5" />}
          accent="purple"
        />
        <StatCard
          label="Sources Online"
          value={sourcesOnline}
          icon={<RadioIcon className="h-5 w-5" />}
          accent="emerald"
        />
        <StatCard
          label="Quarantined Records"
          value={totalQuarantined}
          icon={<AlertTriangleIcon className="h-5 w-5" />}
          accent="amber"
        />
      </section>

      <section className="grid gap-4 xl:grid-cols-[2fr_1fr]">
        <div className="grid gap-4 sm:grid-cols-2">
          {health.map((source) => {
            const SourceIcon = SOURCE_ICON[source.id] ?? DatabaseIcon;
            return (
              <Card key={source.id} interactive glow="cyan" className="p-5">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-start gap-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent-cyan/10 text-accent-cyan">
                      <SourceIcon className="h-4 w-4" />
                    </span>
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-text-primary">
                        {source.title}
                      </p>
                      <p className="truncate text-xs text-text-secondary">
                        {source.source}
                      </p>
                    </div>
                  </div>
                  <Badge
                    variant={source.status === "ready" ? "success" : "danger"}
                    data-testid={sourceHealthTestId(source.id)}
                    className="shrink-0"
                  >
                    {source.status}
                  </Badge>
                </div>
                <div className="mt-4 space-y-1.5 text-sm text-text-secondary">
                  <p>Last ingest: {formatDate(source.ingestAt)}</p>
                  <p>
                    Accepted:{" "}
                    <span className="font-semibold text-text-primary">
                      {source.accepted}
                    </span>
                  </p>
                  <p>Collapsed: {source.collapsed}</p>
                  <p>Quarantined: {source.quarantined}</p>
                </div>
              </Card>
            );
          })}
        </div>

        <Card as="div" className="space-y-4 p-5">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <h2 className="text-lg font-semibold text-text-primary">
                Simulator Controls
              </h2>
              <p className="text-sm text-text-secondary">
                Start, stop, reset, or trigger a scenario. Buttons are
                idempotent and disabled while transitioning.
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-1.5 rounded-full border border-border-subtle bg-surface px-3 py-1 text-sm font-medium text-text-secondary">
              <ClockIcon className="h-3.5 w-3.5" />
              {formatClock(clock)}
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <Button
              variant="primary"
              data-testid={TEST_IDS.simulatorStart}
              disabled={transitioning}
              aria-label="Start simulator"
              onClick={() => handleSimulatorAction("start")}
            >
              Start
            </Button>
            <Button
              variant="secondary"
              data-testid={TEST_IDS.simulatorStop}
              disabled={transitioning}
              aria-label="Stop simulator"
              onClick={() => handleSimulatorAction("stop")}
            >
              Stop
            </Button>
            <Button
              variant="secondary"
              data-testid={TEST_IDS.simulatorReset}
              disabled={transitioning}
              aria-label="Reset simulator"
              onClick={() => handleSimulatorAction("reset")}
            >
              Reset
            </Button>
            <Button
              variant="warning"
              data-testid={TEST_IDS.scenarioTrigger}
              disabled={transitioning}
              aria-label="Trigger scenario"
              onClick={() => triggerScenario(preferredScenario)}
            >
              Trigger scenario
            </Button>
          </div>

          <label className="block text-sm font-medium text-text-secondary">
            Scenario
            <select
              data-testid="scenario-select"
              value={preferredScenario}
              onChange={(event) => setPreferredScenario(event.target.value)}
              disabled={transitioning}
              aria-label="Choose scenario"
              className="mt-2 block w-full rounded-xl border border-border-strong bg-surface px-3 py-2 text-sm text-text-primary shadow-sm outline-none focus:border-accent-cyan focus:ring-2 focus:ring-accent-cyan/30"
            >
              {scenarios.map((scenario) => (
                <option
                  key={scenario.id}
                  value={scenario.id}
                  className="bg-bg-elevated text-text-primary"
                >
                  {scenario.title}
                </option>
              ))}
            </select>
          </label>

          <p className="glass-inset flex items-center gap-2 px-4 py-3 text-sm text-text-secondary">
            <RadioIcon
              className="h-4 w-4 shrink-0 text-accent-cyan"
              aria-hidden="true"
            />
            State:{" "}
            <span className="font-semibold text-text-primary">
              {statusMessage}
            </span>
          </p>
          <p className="text-sm text-text-muted">
            {scenarioTriggered
              ? "Scenario active and the baseline has been replaced."
              : "Baseline running; no incident has been triggered yet."}
          </p>
        </Card>
      </section>

      <Card as="section" className="p-5">
        <header className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold text-text-primary">
              Recent Anomalies
            </h2>
            <p className="text-sm text-text-secondary">
              Last 20 records update automatically as the system polls.
            </p>
          </div>
          <Badge variant="info" hideIcon>
            Polling
          </Badge>
        </header>

        <div className="mt-4 overflow-x-auto rounded-2xl border border-border-subtle">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-white/[0.03] text-text-secondary">
              <tr>
                <th className="sticky top-0 bg-white/[0.03] px-4 py-3 font-semibold">
                  Entity
                </th>
                <th className="sticky top-0 bg-white/[0.03] px-4 py-3 font-semibold">
                  Type
                </th>
                <th className="sticky top-0 bg-white/[0.03] px-4 py-3 font-semibold">
                  Score
                </th>
                <th className="sticky top-0 bg-white/[0.03] px-4 py-3 font-semibold">
                  Detector
                </th>
                <th className="sticky top-0 bg-white/[0.03] px-4 py-3 font-semibold">
                  Time
                </th>
              </tr>
            </thead>
            <tbody>
              {anomalies.slice(0, 20).map((anomaly) => (
                <tr
                  key={anomaly.anomalyId}
                  className="border-t border-border-subtle transition-colors hover:bg-white/[0.03]"
                >
                  <td className="px-4 py-3 font-medium text-text-primary">
                    {anomaly.entity}
                  </td>
                  <td className="px-4 py-3 text-text-secondary">
                    {anomaly.type}
                  </td>
                  <td className="px-4 py-3 font-semibold text-accent-cyan">
                    {anomaly.score.toFixed(1)}
                  </td>
                  <td className="px-4 py-3 text-text-secondary">
                    {anomaly.detectorId}
                  </td>
                  <td className="px-4 py-3 text-text-secondary">
                    {formatDate(anomaly.timestamp)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card as="section" data-testid={TEST_IDS.incidentList} className="p-5">
        <header className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-xl font-semibold text-text-primary">
              Incident List
            </h2>
            <p className="text-sm text-text-secondary">
              Select an incident to investigate the RCA snapshot.
            </p>
          </div>
          <Badge
            variant={severityBadgeVariant(incidentRow.severity)}
            hideIcon
            className="shrink-0"
          >
            {incidentRow.status}
          </Badge>
        </header>

        <div className="mt-4 divide-y divide-border-subtle">
          <a
            data-testid={incidentRowTestId(incidentRow.incidentId)}
            href={`/incidents/${incidentRow.incidentId}`}
            className="group block space-y-3 rounded-2xl p-4 transition-colors hover:bg-white/[0.03]"
          >
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-lg font-semibold text-text-primary transition-colors group-hover:text-accent-cyan">
                  {incidentRow.title}
                </p>
                <p className="mt-1 text-sm text-text-secondary">
                  {incidentRow.affectedEntities.join(", ")}
                </p>
              </div>
              <Badge
                variant={severityBadgeVariant(incidentRow.severity)}
                className="shrink-0"
              >
                {incidentRow.severity}
              </Badge>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <p className="text-sm text-text-secondary">
                Start: {formatDate(incidentRow.startTime)}
              </p>
              <p className="text-sm text-text-secondary">
                Status: {incidentRow.status}
              </p>
            </div>
          </a>
        </div>
      </Card>
    </main>
  );
}
