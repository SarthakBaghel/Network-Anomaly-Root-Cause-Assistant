import { useCallback, useMemo, useRef, useState } from "react";

import type { components } from "../contracts/openapi";
import { anomaliesApi } from "../api/anomalies";
import { ApiClientError } from "../api/client";
import { incidentsApi } from "../api/incidents";
import { simulatorApi } from "../api/simulator";
import { usePolling } from "../hooks/usePolling";
import {
  TEST_IDS,
  anomalyRowTestId,
  incidentRowTestId,
  sourceHealthTestId,
} from "../test-fixtures/testid-manifest";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
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

type SimulatorStatus = components["schemas"]["SimulatorStatusResponse"];
type OverviewAnomaly = components["schemas"]["OverviewAnomaly"];
type IncidentSummary = components["schemas"]["IncidentSummary"];

const scenarios = [
  { id: "gateway_rate_limit_disabled", title: "Gateway rate-limit disabled" },
];

const SOURCE_ICON: Record<string, typeof ActivityIcon> = {
  "simulator.prometheus": ActivityIcon,
  "simulator.syslog": FileTextIcon,
  "simulator.alertmanager": BellIcon,
  "simulator.config_audit": SettingsIcon,
  "fixture.cmdb_topology": NetworkIcon,
};

function formatDate(timestamp?: string | null) {
  if (!timestamp) return "No records yet";
  return new Date(timestamp).toLocaleString("en-US", {
    hour12: false,
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function displayError(error: unknown) {
  if (error instanceof ApiClientError) {
    return `${error.payload.code}: ${error.payload.message}`;
  }
  return "UNEXPECTED_ERROR: The request could not be completed.";
}

function severityLabel(value: number) {
  if (value >= 0.9) return "critical";
  if (value >= 0.75) return "high";
  if (value >= 0.5) return "medium";
  return "low";
}

function severityBadgeVariant(value: number) {
  const severity = severityLabel(value);
  if (severity === "critical") return "danger" as const;
  if (severity === "high" || severity === "medium") return "warning" as const;
  return "success" as const;
}

function incidentStatusVariant(status: IncidentSummary["status"]) {
  if (status === "resolved") return "success" as const;
  if (status === "rejected") return "danger" as const;
  if (status === "investigating") return "info" as const;
  return "warning" as const;
}

export function OverviewPage() {
  const [status, setStatus] = useState<SimulatorStatus | null>(null);
  const [anomalies, setAnomalies] = useState<OverviewAnomaly[]>([]);
  const [incidents, setIncidents] = useState<IncidentSummary[]>([]);
  const [preferredScenario, setPreferredScenario] = useState(scenarios[0].id);
  const [transitioning, setTransitioning] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);
  const latestStatusAt = useRef(0);
  const latestAnomaliesAt = useRef(0);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const [nextStatus, anomalyEnvelope, incidentEnvelope] = await Promise.all([
        simulatorApi.status(),
        anomaliesApi.list(20),
        incidentsApi.list(),
      ]);
      if (signal?.aborted) return;

      const statusAt = Date.parse(nextStatus.generated_at);
      if (Number.isNaN(statusAt) || statusAt >= latestStatusAt.current) {
        latestStatusAt.current = Number.isNaN(statusAt) ? latestStatusAt.current : statusAt;
        setStatus(nextStatus);
      }
      const anomaliesAt = Date.parse(anomalyEnvelope.generated_at);
      if (Number.isNaN(anomaliesAt) || anomaliesAt >= latestAnomaliesAt.current) {
        latestAnomaliesAt.current = Number.isNaN(anomaliesAt) ? latestAnomaliesAt.current : anomaliesAt;
        setAnomalies(anomalyEnvelope.items.slice(0, 20));
      }
      setIncidents(incidentEnvelope.items);
      setApiError(null);
    } catch (error) {
      if (!signal?.aborted) setApiError(displayError(error));
    }
  }, []);

  usePolling(refresh);

  const runAction = async (action: "start" | "stop" | "reset") => {
    setTransitioning(true);
    setApiError(null);
    try {
      const next = await simulatorApi[action]();
      setStatus(next);
      if (action === "reset") {
        setAnomalies([]);
        setIncidents([]);
      }
      await refresh();
    } catch (error) {
      setApiError(displayError(error));
    } finally {
      setTransitioning(false);
    }
  };

  const triggerScenario = async () => {
    setTransitioning(true);
    setApiError(null);
    try {
      setStatus(await simulatorApi.trigger(preferredScenario));
      await refresh();
    } catch (error) {
      setApiError(displayError(error));
    } finally {
      setTransitioning(false);
    }
  };

  const health = status?.source_health ?? [];
  const hasQuarantine = health.some((source) => source.quarantined > 0);
  const totalAccepted = useMemo(() => health.reduce((sum, source) => sum + source.accepted, 0), [health]);
  const totalQuarantined = useMemo(() => health.reduce((sum, source) => sum + source.quarantined, 0), [health]);
  const sourcesOnline = useMemo(() => health.filter((source) => source.status === "ready").length, [health]);
  const scenarioTriggered = status?.scenario_state === "triggering" || status?.scenario_state === "completed";

  return (
    <main className="mx-auto max-w-6xl space-y-8 p-4 sm:p-6 lg:p-8">
      <header className="animate-fade-in-up">
        <p className="text-xs font-bold uppercase tracking-[0.3em] text-accent-cyan">Operations</p>
        <h1 className="mt-2 text-3xl font-extrabold tracking-tight text-text-primary sm:text-4xl">Network Anomaly RCA</h1>
        <p className="mt-2 max-w-2xl text-sm text-text-secondary sm:text-base">Live source health, deterministic simulator control, recent anomalies, and incident navigation.</p>
      </header>

      {apiError ? <div role="alert" aria-live="assertive" data-testid={TEST_IDS.genericBanner} className="glass-panel flex items-center gap-3 border-accent-red/30 bg-accent-red/10 px-4 py-3 text-sm text-accent-red"><AlertTriangleIcon className="h-4 w-4" aria-hidden="true" /><strong>{apiError}</strong></div> : null}
      {hasQuarantine ? <div role="status" aria-live="polite" data-testid={TEST_IDS.quarantineBanner} className="glass-panel flex items-center gap-3 border-accent-amber/30 bg-accent-amber/10 px-4 py-3 text-sm text-accent-amber"><AlertTriangleIcon className="h-4 w-4" aria-hidden="true" />Quarantine warning: {totalQuarantined} source record{totalQuarantined === 1 ? "" : "s"} require attention.</div> : null}

      <section aria-label="Operations totals" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Events Accepted" value={totalAccepted} icon={<GaugeIcon className="h-5 w-5" />} accent="cyan" />
        <StatCard label="Anomalies Detected" value={anomalies.length} icon={<ActivityIcon className="h-5 w-5" />} accent="purple" />
        <StatCard label="Sources Online (of 5)" value={sourcesOnline} icon={<RadioIcon className="h-5 w-5" />} accent="emerald" />
        <StatCard label="Quarantined Records" value={totalQuarantined} icon={<AlertTriangleIcon className="h-5 w-5" />} accent="amber" />
      </section>

      <section className="grid gap-4 xl:grid-cols-[2fr_1fr]">
        <div className="grid gap-4 sm:grid-cols-2" aria-label="Source health">
          {health.length === 0 ? <div data-testid={TEST_IDS.overviewLoading}><EmptyState message="Loading source health…" /></div> : health.map((source) => {
            const SourceIcon = SOURCE_ICON[source.source_id] ?? DatabaseIcon;
            return <Card key={source.source_id} className="p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-3"><span className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent-cyan/10 text-accent-cyan"><SourceIcon className="h-4 w-4" aria-hidden="true" /></span><div><p className="text-sm font-semibold text-text-primary">{source.source_id}</p><p className="text-xs text-text-secondary">{source.source_type}{source.fixture_version ? ` · ${source.fixture_version}` : ""}</p></div></div>
                <Badge variant={source.status === "ready" ? "success" : "danger"} data-testid={sourceHealthTestId(source.source_id)}>{source.status === "ready" ? "✓ ready" : "⚠ error"}</Badge>
              </div>
              <dl className="mt-4 space-y-1.5 text-sm text-text-secondary"><div>Last ingest: {formatDate(source.last_ingest_at)}</div><div>Accepted: <strong className="text-text-primary">{source.accepted}</strong></div><div>Collapsed: {source.collapsed}</div><div>Quarantined: {source.quarantined}</div></dl>
            </Card>;
          })}
        </div>

        <Card as="section" className="space-y-4 p-5">
          <div className="flex items-start justify-between gap-3"><div><h2 className="text-lg font-semibold text-text-primary">Simulator Controls</h2><p className="text-sm text-text-secondary">Actions are idempotent and disabled during transitions.</p></div><div className="flex items-center gap-1.5 rounded-full border border-border-subtle px-3 py-1 text-sm text-text-secondary"><ClockIcon className="h-3.5 w-3.5" aria-hidden="true" />{formatDate(status?.virtual_clock)}</div></div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Button variant="primary" data-testid={TEST_IDS.simulatorStart} disabled={transitioning} aria-label="Start simulator" onClick={() => void runAction("start")}>Start</Button>
            <Button variant="secondary" data-testid={TEST_IDS.simulatorStop} disabled={transitioning} aria-label="Stop simulator" onClick={() => void runAction("stop")}>Stop</Button>
            <Button variant="secondary" data-testid={TEST_IDS.simulatorReset} disabled={transitioning} aria-label="Reset simulator" onClick={() => void runAction("reset")}>Reset</Button>
            <Button variant="warning" data-testid={TEST_IDS.scenarioTrigger} disabled={transitioning} aria-label="Trigger selected scenario" onClick={() => void triggerScenario()}>Trigger scenario</Button>
          </div>
          <label className="block text-sm font-medium text-text-secondary">Scenario<select data-testid={TEST_IDS.scenarioSelect} value={preferredScenario} onChange={(event) => setPreferredScenario(event.target.value)} disabled={transitioning} aria-label="Choose scenario" className="mt-2 block w-full rounded-xl border border-border-strong bg-surface px-3 py-2 text-sm text-text-primary">{scenarios.map((scenario) => <option key={scenario.id} value={scenario.id}>{scenario.title}</option>)}</select></label>
          <p data-testid={TEST_IDS.simulatorState} aria-live="polite" className="glass-inset flex items-center gap-2 px-4 py-3 text-sm text-text-secondary"><RadioIcon className="h-4 w-4 text-accent-cyan" aria-hidden="true" />State: <strong className="text-text-primary">{transitioning ? "transitioning" : status?.state ?? "loading"}</strong></p>
          <p className="text-sm text-text-muted">{scenarioTriggered ? `Scenario active: ${status?.scenario_id}` : status?.scenario_state === "baseline" || status?.scenario_state === "baseline_complete" ? "Baseline running; no incident has been triggered yet." : "Scenario not triggered"}</p>
        </Card>
      </section>

      <Card as="section" className="p-5" data-testid={TEST_IDS.anomalyTable}>
        <header><h2 className="text-xl font-semibold text-text-primary">Recent Anomalies</h2><p className="text-sm text-text-secondary">The latest 20 detector records, refreshed every poll.</p></header>
        {anomalies.length === 0 ? <div className="mt-4"><EmptyState message="No anomalies detected yet." /></div> : <div className="mt-4 overflow-x-auto rounded-2xl border border-border-subtle"><table className="min-w-full text-left text-sm"><thead className="bg-white/[0.03] text-text-secondary"><tr><th className="px-4 py-3">Entity</th><th className="px-4 py-3">Type</th><th className="px-4 py-3">Score</th><th className="px-4 py-3">Detector</th><th className="px-4 py-3">Time</th></tr></thead><tbody>{anomalies.map((anomaly) => <tr key={anomaly.anomaly_id} data-testid={anomalyRowTestId(anomaly.anomaly_id)} className="border-t border-border-subtle"><td className="px-4 py-3 font-medium text-text-primary">{anomaly.entity_id}</td><td className="px-4 py-3 text-text-secondary">{anomaly.anomaly_type}</td><td className="px-4 py-3 font-semibold text-accent-cyan">{(anomaly.score * 100).toFixed(1)}</td><td className="px-4 py-3 text-text-secondary">{anomaly.detector_id}</td><td className="px-4 py-3 text-text-secondary">{formatDate(anomaly.detected_at)}</td></tr>)}</tbody></table></div>}
      </Card>

      <Card as="section" data-testid={TEST_IDS.incidentList} className="p-5">
        <header><h2 className="text-xl font-semibold text-text-primary">Incident List</h2><p className="text-sm text-text-secondary">Select an incident to investigate its current RCA snapshot.</p></header>
        {incidents.length === 0 ? <div className="mt-4"><EmptyState message={scenarioTriggered ? "Scenario is processing; no incident is available yet." : "Baseline running; no incident yet."} /></div> : <div className="mt-4 divide-y divide-border-subtle">{incidents.map((incident) => <a key={incident.incident_id} data-testid={incidentRowTestId(incident.incident_id)} aria-label={`Open incident ${incident.title}`} href={`/incidents/${incident.incident_id}`} className="group block rounded-2xl p-4 hover:bg-white/[0.03]"><div className="flex items-center justify-between gap-3"><div><p className="text-lg font-semibold text-text-primary group-hover:text-accent-cyan">{incident.title}</p><p className="mt-1 text-sm text-text-secondary">{incident.affected_entity_ids.join(", ")}</p></div><Badge variant={severityBadgeVariant(incident.severity)}>⚠ {severityLabel(incident.severity)}</Badge></div><div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm text-text-secondary"><p>Start: {formatDate(incident.started_at)}</p><Badge variant={incidentStatusVariant(incident.status)}>● {incident.status}</Badge></div></a>)}</div>}
      </Card>
    </main>
  );
}
