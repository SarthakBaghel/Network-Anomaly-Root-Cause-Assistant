import { useCallback, useMemo, useRef, useState } from "react";

import type { components } from "../contracts/openapi";
import { anomaliesApi } from "../api/anomalies";
import { ApiClientError } from "../api/client";
import { eventsApi } from "../api/events";
import { incidentsApi } from "../api/incidents";
import { simulatorApi } from "../api/simulator";
import { usePolling } from "../hooks/usePolling";
import {
  TEST_IDS,
  anomalyRowTestId,
  incidentRowTestId,
  sourceHealthTestId,
} from "../test-fixtures/testid-manifest";
import { Badge, type BadgeVariant } from "../components/ui/Badge";
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
type SimulatorScenario = components["schemas"]["SimulatorScenario"];
type OverviewAnomaly = components["schemas"]["OverviewAnomaly"];
type IncidentSummary = components["schemas"]["IncidentSummary"];
type CanonicalEvent = components["schemas"]["CanonicalEvent"];

const SOURCE_ICON: Record<string, typeof ActivityIcon> = {
  "simulator.prometheus": ActivityIcon,
  "simulator.syslog": FileTextIcon,
  "simulator.alertmanager": BellIcon,
  "simulator.config_audit": SettingsIcon,
  "fixture.cmdb_topology": NetworkIcon,
};

const LIFECYCLE_STEPS = ["Reset", "Baseline", "Ready", "Scenario"] as const;

function formatDate(timestamp?: string | null) {
  if (!timestamp) return "Not available";
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

function healthBadge(status: SimulatorStatus["source_health"][number]["status"]): {
  variant: BadgeVariant;
  label: string;
} {
  if (status === "healthy") return { variant: "success", label: "healthy" };
  if (status === "delayed") return { variant: "warning", label: "delayed" };
  if (status === "quarantined") return { variant: "warning", label: "quarantined" };
  if (status === "offline") return { variant: "neutral", label: "offline" };
  return { variant: "danger", label: "error" };
}

function friendlyLabel(value: string) {
  const words = value.toLowerCase().replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function lifecycleIndex(status: SimulatorStatus | null) {
  if (!status || status.scenario_state === "idle") return 0;
  if (status.scenario_state === "baseline") return 1;
  if (status.scenario_state === "baseline_complete") return 2;
  return 3;
}

export function OverviewPage() {
  const [status, setStatus] = useState<SimulatorStatus | null>(null);
  const [scenarios, setScenarios] = useState<SimulatorScenario[]>([]);
  const [anomalies, setAnomalies] = useState<OverviewAnomaly[]>([]);
  const [incidents, setIncidents] = useState<IncidentSummary[]>([]);
  const [preferredScenario, setPreferredScenario] = useState("");
  const [transitioning, setTransitioning] = useState(false);
  const [confirmingReset, setConfirmingReset] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);
  const [entityFilter, setEntityFilter] = useState("all");
  const [typeFilter, setTypeFilter] = useState("all");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [severityFilter, setSeverityFilter] = useState("all");
  const [timeFilter, setTimeFilter] = useState("all");
  const [expandedAnomalyId, setExpandedAnomalyId] = useState<string | null>(null);
  const [eventsById, setEventsById] = useState<Record<string, CanonicalEvent>>({});
  const latestStatusAt = useRef(0);
  const latestAnomaliesAt = useRef(0);
  const latestIncidentsAt = useRef(0);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const [nextStatus, scenarioEnvelope, anomalyEnvelope, incidentEnvelope] =
        await Promise.all([
          simulatorApi.status(signal),
          simulatorApi.listScenarios(signal),
          anomaliesApi.list(100, signal),
          incidentsApi.list(signal),
        ]);
      if (signal?.aborted) return;

      const statusAt = Date.parse(nextStatus.generated_at);
      if (Number.isNaN(statusAt) || statusAt >= latestStatusAt.current) {
        latestStatusAt.current = Number.isNaN(statusAt) ? latestStatusAt.current : statusAt;
        setStatus(nextStatus);
      }
      const anomaliesAt = Date.parse(anomalyEnvelope.generated_at);
      if (Number.isNaN(anomaliesAt) || anomaliesAt >= latestAnomaliesAt.current) {
        latestAnomaliesAt.current = Number.isNaN(anomaliesAt)
          ? latestAnomaliesAt.current
          : anomaliesAt;
        setAnomalies(anomalyEnvelope.items);
      }
      const incidentsAt = Date.parse(incidentEnvelope.generated_at);
      if (Number.isNaN(incidentsAt) || incidentsAt >= latestIncidentsAt.current) {
        latestIncidentsAt.current = Number.isNaN(incidentsAt)
          ? latestIncidentsAt.current
          : incidentsAt;
        setIncidents(incidentEnvelope.items);
      }
      setScenarios(scenarioEnvelope.items);
      setPreferredScenario((current) =>
        scenarioEnvelope.items.some((scenario) => scenario.scenario_id === current)
          ? current
          : (scenarioEnvelope.items[0]?.scenario_id ?? ""),
      );
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
        setEventsById({});
        setExpandedAnomalyId(null);
      }
      await refresh();
    } catch (error) {
      setApiError(displayError(error));
    } finally {
      setTransitioning(false);
    }
  };

  const triggerScenario = async () => {
    if (!preferredScenario) return;
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

  const toggleAnomaly = async (anomaly: OverviewAnomaly) => {
    if (expandedAnomalyId === anomaly.anomaly_id) {
      setExpandedAnomalyId(null);
      return;
    }
    setExpandedAnomalyId(anomaly.anomaly_id);
    if (eventsById[anomaly.event_id]) return;
    try {
      const event = await eventsApi.get(anomaly.event_id);
      setEventsById((current) => ({ ...current, [anomaly.event_id]: event }));
    } catch (error) {
      setApiError(displayError(error));
    }
  };

  const health = status?.source_health ?? [];
  const totalAccepted = useMemo(
    () => health.reduce((sum, source) => sum + source.accepted, 0),
    [health],
  );
  const totalQuarantined = useMemo(
    () => health.reduce((sum, source) => sum + source.quarantined, 0),
    [health],
  );
  const sourcesOnline = useMemo(
    () => health.filter((source) => ["healthy", "delayed"].includes(source.status)).length,
    [health],
  );
  const actionableAnomalies = useMemo(
    () => anomalies.filter((anomaly) => !anomaly.context_only && anomaly.can_open_incident),
    [anomalies],
  );
  const contextMarkers = useMemo(
    () => anomalies.filter((anomaly) => anomaly.context_only),
    [anomalies],
  );
  const entities = useMemo(
    () => [...new Set(anomalies.map((anomaly) => anomaly.entity_id))].sort(),
    [anomalies],
  );
  const anomalyTypes = useMemo(
    () => [...new Set(anomalies.map((anomaly) => anomaly.anomaly_type))].sort(),
    [anomalies],
  );
  const sources = useMemo(
    () => [...new Set(anomalies.map((anomaly) => anomaly.source))].sort(),
    [anomalies],
  );
  const filteredAnomalies = useMemo(() => {
    const virtualNow = status ? Date.parse(status.virtual_clock) : Number.NaN;
    const windowMs = timeFilter === "1m" ? 60_000 : timeFilter === "5m" ? 300_000 : null;
    return anomalies.filter((anomaly) => {
      if (entityFilter !== "all" && anomaly.entity_id !== entityFilter) return false;
      if (typeFilter !== "all" && anomaly.anomaly_type !== typeFilter) return false;
      if (sourceFilter !== "all" && anomaly.source !== sourceFilter) return false;
      if (severityFilter !== "all" && severityLabel(anomaly.severity) !== severityFilter) {
        return false;
      }
      if (windowMs !== null && !Number.isNaN(virtualNow)) {
        const detectedAt = Date.parse(anomaly.detected_at);
        if (!Number.isNaN(detectedAt) && virtualNow - detectedAt > windowMs) return false;
      }
      return true;
    });
  }, [anomalies, entityFilter, severityFilter, sourceFilter, status, timeFilter, typeFilter]);

  const selectedScenario = scenarios.find(
    (scenario) => scenario.scenario_id === preferredScenario,
  );
  const hasQuarantine = totalQuarantined > 0;
  const scenarioTriggered = ["triggering", "completed"].includes(
    status?.scenario_state ?? "",
  );
  const canStart =
    status?.state === "stopped" &&
    status.last_reset_at !== null &&
    status.scenario_id === null &&
    ["idle", "baseline"].includes(status.scenario_state);
  const canStop = status?.state === "running";
  const canTrigger =
    status?.state === "ready" &&
    status.scenario_state === "baseline_complete" &&
    status.scenario_id === null;
  const activeLifecycleIndex = lifecycleIndex(status);
  const baselinePercent = status?.baseline_ticks_required
    ? Math.round((status.baseline_ticks_emitted / status.baseline_ticks_required) * 100)
    : 0;

  const statusMessage = status?.last_reset_at === null
    ? "Reset data before running the baseline."
    : scenarioTriggered
      ? `Scenario completed: ${status?.scenario_id}`
      : status?.scenario_state === "baseline_complete"
        ? "Baseline complete — ready to trigger."
        : status?.scenario_state === "baseline"
          ? `Replaying baseline: ${status.baseline_ticks_emitted}/${status.baseline_ticks_required}`
          : "Run the baseline before triggering a scenario.";

  return (
    <main className="mx-auto max-w-7xl space-y-8 p-4 sm:p-6 lg:p-8">
      <header className="animate-fade-in-up">
        <p className="text-xs font-bold uppercase tracking-[0.3em] text-accent-cyan">Operations</p>
        <h1 className="mt-2 text-3xl font-extrabold tracking-tight text-text-primary sm:text-4xl">
          Network Anomaly RCA
        </h1>
        <p className="mt-2 max-w-3xl text-sm text-text-secondary sm:text-base">
          Replay a clean baseline, trigger a catalogue-backed network failure, and inspect
          the resulting evidence and root-cause analysis.
        </p>
      </header>

      {apiError ? (
        <div
          role="alert"
          aria-live="assertive"
          data-testid={TEST_IDS.genericBanner}
          className="glass-panel flex items-center gap-3 border-accent-red/30 bg-accent-red/10 px-4 py-3 text-sm text-accent-red"
        >
          <AlertTriangleIcon className="h-4 w-4" aria-hidden="true" />
          <strong>{apiError}</strong>
        </div>
      ) : null}
      {hasQuarantine ? (
        <div
          role="status"
          aria-live="polite"
          data-testid={TEST_IDS.quarantineBanner}
          className="glass-panel flex items-center gap-3 border-accent-amber/30 bg-accent-amber/10 px-4 py-3 text-sm text-accent-amber"
        >
          <AlertTriangleIcon className="h-4 w-4" aria-hidden="true" />
          Quarantine warning: {totalQuarantined} source record
          {totalQuarantined === 1 ? "" : "s"} require attention.
        </div>
      ) : null}

      <section aria-label="Operations totals" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Events Accepted" value={totalAccepted} icon={<GaugeIcon className="h-5 w-5" />} accent="cyan" />
        <StatCard label="Actionable Anomalies" value={actionableAnomalies.length} icon={<ActivityIcon className="h-5 w-5" />} accent="purple" />
        <StatCard label={`Sources Online (of ${health.length})`} value={sourcesOnline} icon={<RadioIcon className="h-5 w-5" />} accent="emerald" />
        <StatCard label="Context Markers" value={contextMarkers.length} icon={<FileTextIcon className="h-5 w-5" />} accent="amber" />
      </section>

      <Card as="section" className="p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-text-primary">Scenario lifecycle</h2>
            <p className="text-sm text-text-secondary">Reset data before starting a new investigation run.</p>
          </div>
          <div className="grid flex-1 grid-cols-4 gap-2 lg:max-w-2xl">
            {LIFECYCLE_STEPS.map((step, index) => (
              <div
                key={step}
                className={`rounded-xl border px-2 py-2 text-center text-xs font-semibold ${
                  index < activeLifecycleIndex
                    ? "border-accent-emerald/30 bg-accent-emerald/10 text-accent-emerald"
                    : index === activeLifecycleIndex
                      ? "border-accent-cyan/40 bg-accent-cyan/10 text-accent-cyan"
                      : "border-border-subtle text-text-muted"
                }`}
              >
                {index + 1}. {step}
              </div>
            ))}
          </div>
        </div>
      </Card>

      <section className="grid gap-4 xl:grid-cols-[2fr_1fr]">
        <div className="grid gap-4 sm:grid-cols-2" aria-label="Source health">
          {health.length === 0 ? (
            <div data-testid={TEST_IDS.overviewLoading}>
              <EmptyState message="Loading source health…" />
            </div>
          ) : (
            health.map((source) => {
              const SourceIcon = SOURCE_ICON[source.source_id] ?? DatabaseIcon;
              const healthPresentation = healthBadge(source.status);
              return (
                <Card key={source.source_id} className="p-5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex min-w-0 items-start gap-3">
                      <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent-cyan/10 text-accent-cyan">
                        <SourceIcon className="h-4 w-4" aria-hidden="true" />
                      </span>
                      <div>
                        <p className="text-sm font-semibold text-text-primary">{source.source_id}</p>
                        <p className="text-xs text-text-secondary">
                          {source.source_type}
                          {source.fixture_version ? ` · ${source.fixture_version}` : ""}
                        </p>
                      </div>
                    </div>
                    <Badge
                      variant={healthPresentation.variant}
                      data-testid={sourceHealthTestId(source.source_id)}
                    >
                      {healthPresentation.label}
                    </Badge>
                  </div>
                  <dl className="mt-4 space-y-1.5 text-sm text-text-secondary">
                    <div>Last ingest: {formatDate(source.last_ingest_at)}</div>
                    <div>Accepted: <strong className="text-text-primary">{source.accepted}</strong></div>
                    <div>Collapsed: {source.collapsed}</div>
                    <div>Quarantined: {source.quarantined}</div>
                  </dl>
                </Card>
              );
            })
          )}
        </div>

        <Card as="section" className="space-y-4 p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-text-primary">Simulator Controls</h2>
              <p className="text-sm text-text-secondary">Finite, deterministic baseline replay.</p>
            </div>
            <div className="flex items-center gap-1.5 rounded-full border border-border-subtle px-3 py-1 text-sm text-text-secondary">
              <ClockIcon className="h-3.5 w-3.5" aria-hidden="true" />
              {formatDate(status?.virtual_clock)}
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <Button variant="primary" data-testid={TEST_IDS.simulatorStart} disabled={transitioning || !canStart} onClick={() => void runAction("start")}>
              Run baseline
            </Button>
            <Button variant="secondary" data-testid={TEST_IDS.simulatorStop} disabled={transitioning || !canStop} onClick={() => void runAction("stop")}>
              Stop
            </Button>
            <Button variant="danger" data-testid={TEST_IDS.simulatorReset} disabled={transitioning} onClick={() => setConfirmingReset(true)}>
              Reset data
            </Button>
            <Button variant="warning" data-testid={TEST_IDS.scenarioTrigger} disabled={transitioning || !canTrigger || !preferredScenario} onClick={() => void triggerScenario()}>
              Trigger scenario
            </Button>
          </div>

          {confirmingReset ? (
            <div role="dialog" aria-label="Confirm simulator reset" className="rounded-2xl border border-accent-red/30 bg-accent-red/10 p-4 text-sm text-text-secondary">
              <p><strong className="text-text-primary">Delete the current demo investigation?</strong></p>
              <p className="mt-1">This clears anomalies, incidents, reviews, and audit records.</p>
              <div className="mt-3 flex gap-2">
                <Button variant="ghost" onClick={() => setConfirmingReset(false)}>Cancel</Button>
                <Button
                  variant="danger"
                  data-testid={TEST_IDS.simulatorResetConfirm}
                  onClick={() => {
                    setConfirmingReset(false);
                    void runAction("reset");
                  }}
                >
                  Confirm reset
                </Button>
              </div>
            </div>
          ) : null}

          <label className="block text-sm font-medium text-text-secondary">
            Scenario
            <select
              data-testid={TEST_IDS.scenarioSelect}
              value={preferredScenario}
              onChange={(event) => setPreferredScenario(event.target.value)}
              disabled={transitioning || scenarios.length === 0}
              className="mt-2 block w-full rounded-xl border border-border-strong bg-surface px-3 py-2 text-sm text-text-primary"
            >
              {scenarios.map((scenario) => (
                <option key={scenario.scenario_id} value={scenario.scenario_id}>{scenario.title}</option>
              ))}
            </select>
          </label>

          {selectedScenario ? (
            <div className="glass-inset space-y-2 px-4 py-3 text-sm text-text-secondary">
              <div className="flex items-center justify-between gap-2">
                <strong className="text-text-primary">{selectedScenario.title}</strong>
                <Badge variant="info">{selectedScenario.difficulty}</Badge>
              </div>
              <p>{selectedScenario.description}</p>
              <p>Affects: {selectedScenario.affected_entity_ids.join(", ")}</p>
              <p>Signals: {selectedScenario.expected_signals.join(", ")}</p>
            </div>
          ) : null}

          <p data-testid={TEST_IDS.simulatorState} aria-live="polite" className="glass-inset flex items-center gap-2 px-4 py-3 text-sm text-text-secondary">
            <RadioIcon className="h-4 w-4 text-accent-cyan" aria-hidden="true" />
            State: <strong className="text-text-primary">{transitioning ? "transitioning" : status?.state ?? "loading"}</strong>
          </p>
          <div>
            <div className="mb-1 flex justify-between text-xs text-text-muted">
              <span>{statusMessage}</span><span>{baselinePercent}%</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-white/5">
              <div className="h-full rounded-full bg-gradient-to-r from-accent-cyan to-accent-purple transition-all" style={{ width: `${baselinePercent}%` }} />
            </div>
          </div>
          <dl className="grid grid-cols-2 gap-2 text-xs text-text-muted">
            <div>Scenario ID<br /><strong className="text-text-secondary">{status?.scenario_id ?? "Not triggered"}</strong></div>
            <div>Last reset<br /><strong className="text-text-secondary">{formatDate(status?.last_reset_at)}</strong></div>
          </dl>
        </Card>
      </section>

      <Card as="section" className="p-5" data-testid={TEST_IDS.anomalyTable}>
        <header className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h2 className="text-xl font-semibold text-text-primary">Recent detector records</h2>
            <p className="text-sm text-text-secondary">
              {actionableAnomalies.length} actionable anomal{actionableAnomalies.length === 1 ? "y" : "ies"} + {contextMarkers.length} context marker{contextMarkers.length === 1 ? "" : "s"}.
            </p>
          </div>
          <p className="text-xs text-text-muted">Showing {filteredAnomalies.length} of {anomalies.length}</p>
        </header>

        <div data-testid={TEST_IDS.anomalyFilters} className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          <label className="text-xs text-text-secondary">Entity<select aria-label="Filter anomalies by entity" value={entityFilter} onChange={(event) => setEntityFilter(event.target.value)} className="mt-1 w-full rounded-xl border border-border-strong bg-surface px-3 py-2 text-sm text-text-primary"><option value="all">All entities</option>{entities.map((entity) => <option key={entity} value={entity}>{entity}</option>)}</select></label>
          <label className="text-xs text-text-secondary">Type<select aria-label="Filter anomalies by type" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)} className="mt-1 w-full rounded-xl border border-border-strong bg-surface px-3 py-2 text-sm text-text-primary"><option value="all">All types</option>{anomalyTypes.map((type) => <option key={type} value={type}>{friendlyLabel(type)}</option>)}</select></label>
          <label className="text-xs text-text-secondary">Source<select aria-label="Filter anomalies by source" value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)} className="mt-1 w-full rounded-xl border border-border-strong bg-surface px-3 py-2 text-sm text-text-primary"><option value="all">All sources</option>{sources.map((source) => <option key={source} value={source}>{source}</option>)}</select></label>
          <label className="text-xs text-text-secondary">Severity<select aria-label="Filter anomalies by severity" value={severityFilter} onChange={(event) => setSeverityFilter(event.target.value)} className="mt-1 w-full rounded-xl border border-border-strong bg-surface px-3 py-2 text-sm text-text-primary"><option value="all">All severities</option><option value="critical">Critical</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></label>
          <label className="text-xs text-text-secondary">Time<select aria-label="Filter anomalies by time" value={timeFilter} onChange={(event) => setTimeFilter(event.target.value)} className="mt-1 w-full rounded-xl border border-border-strong bg-surface px-3 py-2 text-sm text-text-primary"><option value="all">All records</option><option value="1m">Last virtual minute</option><option value="5m">Last 5 virtual minutes</option></select></label>
        </div>

        {filteredAnomalies.length === 0 ? (
          <div className="mt-4"><EmptyState message={anomalies.length ? "No detector records match the active filters." : "No detector records yet."} /></div>
        ) : (
          <div className="mt-4 overflow-x-auto rounded-2xl border border-border-subtle">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-white/[0.03] text-text-secondary"><tr><th className="px-4 py-3">Entity</th><th className="px-4 py-3">Type</th><th className="px-4 py-3">Severity</th><th className="px-4 py-3">Score</th><th className="px-4 py-3">Source</th><th className="px-4 py-3">Actions</th></tr></thead>
              <tbody>
                {filteredAnomalies.map((anomaly) => {
                  const relatedIncident = incidents.find((incident) => incident.affected_entity_ids.includes(anomaly.entity_id));
                  const rawEvent = eventsById[anomaly.event_id];
                  return [
                    <tr key={anomaly.anomaly_id} data-testid={anomalyRowTestId(anomaly.anomaly_id)} className="border-t border-border-subtle">
                      <td className="px-4 py-3 font-medium text-text-primary">{anomaly.entity_id}</td>
                      <td className="px-4 py-3 text-text-secondary"><span>{friendlyLabel(anomaly.anomaly_type)}</span>{anomaly.context_only ? <Badge className="ml-2" variant="neutral">context</Badge> : null}</td>
                      <td className="px-4 py-3"><Badge variant={severityBadgeVariant(anomaly.severity)}>{severityLabel(anomaly.severity)}</Badge></td>
                      <td className="px-4 py-3 font-semibold text-accent-cyan">{(anomaly.score * 100).toFixed(1)}</td>
                      <td className="px-4 py-3 text-text-secondary">{anomaly.source}</td>
                      <td className="px-4 py-3"><div className="flex gap-2"><Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => void toggleAnomaly(anomaly)}>{expandedAnomalyId === anomaly.anomaly_id ? "Hide" : "Why?"}</Button>{relatedIncident ? <a className="rounded-xl border border-accent-cyan/30 px-2 py-1 text-xs font-semibold text-accent-cyan" href={`/incidents/${relatedIncident.incident_id}`}>Open incident</a> : null}</div></td>
                    </tr>,
                    expandedAnomalyId === anomaly.anomaly_id ? (
                      <tr key={`${anomaly.anomaly_id}-details`} className="border-t border-border-subtle bg-white/[0.02]"><td colSpan={6} className="px-4 py-4"><div className="grid gap-4 lg:grid-cols-2"><div><p className="font-semibold text-text-primary">Why the detector fired</p><p className="mt-1 text-text-secondary">{anomaly.explanation}</p><p className="mt-2 text-xs text-text-muted">Detector: {anomaly.detector_id} · Event: {anomaly.event_id} · {formatDate(anomaly.detected_at)}</p></div><div><p className="font-semibold text-text-primary">Raw event payload</p>{rawEvent ? <pre className="mt-1 max-h-48 overflow-auto rounded-xl bg-slate-950/70 p-3 text-xs text-text-secondary">{JSON.stringify(rawEvent.raw_payload, null, 2)}</pre> : <p className="mt-1 text-text-muted">Loading raw event…</p>}</div></div></td></tr>
                    ) : null,
                  ];
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card as="section" data-testid={TEST_IDS.incidentList} className="p-5">
        <header><h2 className="text-xl font-semibold text-text-primary">Incident List</h2><p className="text-sm text-text-secondary">Select an incident to investigate its current immutable RCA snapshot.</p></header>
        {incidents.length === 0 ? (
          <div className="mt-4"><EmptyState message={scenarioTriggered ? "Scenario completed without a published incident." : status?.scenario_state === "baseline_complete" ? "Baseline complete; choose and trigger a scenario." : "No current-run incident. Reset and run the baseline to begin."} /></div>
        ) : (
          <div className="mt-4 divide-y divide-border-subtle">{incidents.map((incident) => <a key={incident.incident_id} data-testid={incidentRowTestId(incident.incident_id)} aria-label={`Open incident ${incident.title}`} href={`/incidents/${incident.incident_id}`} className="group block rounded-2xl p-4 hover:bg-white/[0.03]"><div className="flex items-center justify-between gap-3"><div><p className="text-lg font-semibold text-text-primary group-hover:text-accent-cyan">{incident.title}</p><p className="mt-1 text-sm text-text-secondary">{incident.affected_entity_ids.join(", ")}</p></div><Badge variant={severityBadgeVariant(incident.severity)}>⚠ {severityLabel(incident.severity)}</Badge></div><div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm text-text-secondary"><p>Start: {formatDate(incident.started_at)}</p><Badge variant={incidentStatusVariant(incident.status)}>● {incident.status}</Badge></div></a>)}</div>
        )}
      </Card>
    </main>
  );
}
