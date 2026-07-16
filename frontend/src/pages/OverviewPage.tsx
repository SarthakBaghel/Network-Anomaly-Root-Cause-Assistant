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
  AlertTriangleIcon,
  ClockIcon,
  RadioIcon,
} from "../components/icons";

type SimulatorStatus = components["schemas"]["SimulatorStatusResponse"];
type SimulatorScenario = components["schemas"]["SimulatorScenario"];
type OverviewAnomaly = components["schemas"]["OverviewAnomaly"];
type IncidentSummary = components["schemas"]["IncidentSummary"];
type CanonicalEvent = components["schemas"]["CanonicalEvent"];

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

function relativeTime(timestamp: string, reference?: string) {
  const end = reference ? Date.parse(reference) : Date.now();
  const start = Date.parse(timestamp);
  if (Number.isNaN(start) || Number.isNaN(end)) return formatDate(timestamp);
  const seconds = Math.max(0, Math.round((end - start) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  return minutes < 60 ? `${minutes}m ago` : formatDate(timestamp);
}

function sourceDot(status: SimulatorStatus["source_health"][number]["status"]) {
  if (status === "healthy") return "bg-accent-emerald";
  if (status === "delayed" || status === "quarantined") return "bg-accent-amber";
  if (status === "offline") return "bg-text-muted";
  return "bg-accent-red";
}

function anomalyTypeClass(source: string) {
  if (source.includes("prometheus")) return "border-accent-cyan/40 text-accent-cyan";
  if (source.includes("syslog")) return "border-accent-emerald/40 text-accent-emerald";
  if (source.includes("alert")) return "border-accent-amber/40 text-accent-amber";
  return "border-accent-purple/40 text-accent-purple";
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
  const [triggeringScenario, setTriggeringScenario] = useState(false);
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

  // A scenario trigger is a deliberate long-running request in LLM mode.
  // Suspend the regular dashboard poll while it is in flight so a short poll
  // timeout cannot overwrite the useful progress state with ECONNABORTED.
  usePolling(refresh, undefined, !transitioning);

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
    setTriggeringScenario(true);
    setApiError(null);
    try {
      setStatus(await simulatorApi.trigger(preferredScenario));
      await refresh();
    } catch (error) {
      setApiError(displayError(error));
    } finally {
      setTriggeringScenario(false);
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

  const statusMessage = triggeringScenario
    ? "Processing scenario evidence and generating the RCA explanation…"
    : status?.last_reset_at === null
    ? "Reset data before running the baseline."
    : scenarioTriggered
      ? `Scenario completed: ${status?.scenario_id}`
      : status?.scenario_state === "baseline_complete"
        ? "Baseline complete — ready to trigger."
        : status?.scenario_state === "baseline"
          ? `Replaying baseline: ${status.baseline_ticks_emitted}/${status.baseline_ticks_required}`
          : "Run the baseline before triggering a scenario.";

  return (
    <main className="mx-auto flex max-w-7xl flex-col gap-6 p-4 sm:p-6 lg:p-8">
      <header className="order-0 border-b border-border-subtle pb-5">
        <p className="text-sm font-medium text-text-secondary">Operations overview</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-text-primary sm:text-3xl">
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
          className="order-1 flex items-center gap-3 rounded border border-l-2 border-border-subtle border-l-accent-red bg-surface px-4 py-3 text-sm text-accent-red"
        >
          <AlertTriangleIcon className="h-4 w-4" aria-hidden="true" />
          <strong>{apiError}</strong>
        </div>
      ) : null}
      <section aria-label="Operations totals" className="order-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Events accepted" value={totalAccepted} accent="cyan" />
        <StatCard label="Actionable anomalies" value={actionableAnomalies.length} accent="purple" />
        <StatCard label={`Sources online / ${health.length}`} value={sourcesOnline} accent="emerald" />
        <StatCard label="Context markers" value={contextMarkers.length} accent="amber" />
      </section>

      <Card as="section" className="order-6 p-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-text-primary">Scenario lifecycle</h2>
            <p className="text-sm text-text-secondary">Reset data before starting a new investigation run.</p>
          </div>
          <div className="grid flex-1 grid-cols-4 gap-2 lg:max-w-2xl">
            {LIFECYCLE_STEPS.map((step, index) => (
              <div
                key={step}
                className={`rounded border px-2 py-1.5 text-center text-xs font-semibold ${
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

      <>
        <Card as="section" className="order-3 p-4" aria-label="Source health">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="mr-2 text-sm font-semibold text-text-primary">Source health</h2>
          {health.length === 0 ? (
            <div data-testid={TEST_IDS.overviewLoading}>
              <EmptyState message="Loading source health…" />
            </div>
          ) : (
            health.map((source) => {
              const healthPresentation = healthBadge(source.status);
              return (
                <details
                  key={source.source_id}
                  data-testid={sourceHealthTestId(source.source_id)}
                  className="group relative"
                >
                  <summary className="font-data flex cursor-pointer list-none items-center gap-2 rounded border border-border-subtle bg-surface-strong px-2.5 py-1.5 text-xs text-text-secondary hover:border-border-strong">
                    <span className={`h-2 w-2 rounded-full ${sourceDot(source.status)}`} />
                    <span>{source.source_id}</span>
                    <span className="text-text-muted">{source.accepted.toLocaleString()}</span>
                    {source.quarantined > 0 ? (
                      <span className="text-accent-amber">q:{source.quarantined}</span>
                    ) : null}
                    <span className="sr-only">{healthPresentation.label}</span>
                  </summary>
                  <dl className="absolute left-0 top-full z-20 mt-1 w-72 rounded border border-border-strong bg-surface-strong p-3 text-xs text-text-secondary shadow-glass-lg">
                    <div>Status: <strong className="text-text-primary">{healthPresentation.label}</strong></div>
                    <div className="mt-1">Type: {source.source_type}</div>
                    <div className="mt-1">Last ingest: <span className="font-data">{formatDate(source.last_ingest_at)}</span></div>
                    <div className="mt-1">Collapsed: {source.collapsed} · Quarantined: {source.quarantined}</div>
                    {source.fixture_version ? <div className="mt-1 font-data">{source.fixture_version}</div> : null}
                  </dl>
                </details>
              );
            })
          )}
          </div>
          {hasQuarantine ? (
            <p
              role="status"
              data-testid={TEST_IDS.quarantineBanner}
              className="mt-3 border-l-2 border-l-accent-amber pl-3 text-xs text-accent-amber"
            >
              {totalQuarantined} source record{totalQuarantined === 1 ? "" : "s"} quarantined
            </p>
          ) : null}
        </Card>

        <Card as="section" className="order-7 space-y-4 p-5">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-text-primary">Simulator Controls</h2>
              <p className="text-sm text-text-secondary">Finite, deterministic baseline replay.</p>
            </div>
            <div className="font-data flex items-center gap-1.5 rounded border border-border-subtle px-3 py-1 text-xs text-text-secondary">
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
              {triggeringScenario ? "Generating RCA…" : "Trigger scenario"}
            </Button>
          </div>

          {confirmingReset ? (
            <div role="dialog" aria-label="Confirm simulator reset" className="rounded-md border border-accent-red/30 bg-accent-red/10 p-4 text-sm text-text-secondary">
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
              className="mt-2 block w-full rounded border border-border-strong bg-surface px-3 py-2 text-sm text-text-primary"
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
                <div className="flex flex-wrap justify-end gap-2">
                  <Badge variant="info">{selectedScenario.difficulty}</Badge>
                  <Badge
                    variant={selectedScenario.quality_flag === "REFERENCE_DERIVED" ? "success" : "neutral"}
                  >
                    {selectedScenario.quality_flag === "REFERENCE_DERIVED"
                      ? "reference-derived"
                      : "synthetic"}
                  </Badge>
                </div>
              </div>
              <p>{selectedScenario.description}</p>
              <p>Affects: {selectedScenario.affected_entity_ids.join(", ")}</p>
              <p>Signals: {selectedScenario.expected_signals.join(", ")}</p>
              {(selectedScenario.reference_datasets ?? []).length > 0 ? (
                <p>
                  Reference data: {(selectedScenario.reference_datasets ?? []).join(", ")} · Transformation: <span className="font-data">{selectedScenario.transformation_version}</span>
                </p>
              ) : (
                <p>Deterministic simulator fixture · <span className="font-data">{selectedScenario.transformation_version}</span></p>
              )}
            </div>
          ) : null}

          <p data-testid={TEST_IDS.simulatorState} aria-live="polite" className="glass-inset font-data flex items-center gap-2 px-4 py-3 text-sm text-text-secondary">
            <RadioIcon className="h-4 w-4 text-accent-cyan" aria-hidden="true" />
            State: <strong className="text-text-primary">{triggeringScenario ? "generating RCA" : transitioning ? "transitioning" : status?.state ?? "loading"}</strong>
          </p>
          <div>
            <div className="mb-1 flex justify-between text-xs text-text-muted">
              <span>{statusMessage}</span><span>{baselinePercent}%</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-white/5">
              <div className="h-full bg-accent-cyan transition-all" style={{ width: `${baselinePercent}%` }} />
            </div>
          </div>
          <dl className="grid grid-cols-2 gap-2 text-xs text-text-muted">
            <div>Scenario ID<br /><strong className="font-data text-text-secondary">{status?.scenario_id ?? "Not triggered"}</strong></div>
            <div>Last reset<br /><strong className="font-data text-text-secondary">{formatDate(status?.last_reset_at)}</strong></div>
          </dl>
        </Card>
      </>

      <Card as="section" className="order-5 p-4" data-testid={TEST_IDS.anomalyTable}>
        <header className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-text-primary">Recent detector records</h2>
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
          <div className="mt-4 overflow-x-auto rounded-md border border-border-subtle">
            <table className="min-w-full text-left text-xs">
              <thead className="bg-surface-strong text-text-secondary"><tr><th className="px-3 py-2">Entity</th><th className="px-3 py-2">Type</th><th className="px-3 py-2">Severity</th><th className="px-3 py-2">Score</th><th className="px-3 py-2">Source</th><th className="px-3 py-2">Detected</th><th className="px-3 py-2">Actions</th></tr></thead>
              <tbody>
                {filteredAnomalies.map((anomaly) => {
                  const relatedIncident = incidents.find((incident) => incident.affected_entity_ids.includes(anomaly.entity_id));
                  const rawEvent = eventsById[anomaly.event_id];
                  return [
                    <tr key={anomaly.anomaly_id} data-testid={anomalyRowTestId(anomaly.anomaly_id)} className="border-t border-border-subtle">
                      <td className="font-data px-3 py-1.5 font-medium text-text-primary">{anomaly.entity_id}</td>
                      <td className="px-3 py-1.5 text-text-secondary"><span className={`inline-flex rounded border px-1.5 py-0.5 ${anomalyTypeClass(anomaly.source)}`}>{friendlyLabel(anomaly.anomaly_type)}</span>{anomaly.context_only ? <span className="font-data ml-1.5 rounded border border-border-strong px-1 py-0.5 text-[0.65rem] text-text-muted">CTX</span> : null}</td>
                      <td className="px-3 py-1.5"><Badge variant={severityBadgeVariant(anomaly.severity)}>{severityLabel(anomaly.severity)}</Badge></td>
                      <td className="px-3 py-1.5"><div className="flex items-center gap-2"><span className="font-data w-10 text-right text-text-primary">{(anomaly.score * 100).toFixed(1)}</span><span className="h-4 w-0.5 bg-border-strong"><span className="block w-0.5 bg-accent-cyan" style={{ height: `${anomaly.score * 100}%` }} /></span></div></td>
                      <td className="font-data px-3 py-1.5 text-text-secondary">{anomaly.source}</td>
                      <td className="font-data whitespace-nowrap px-3 py-1.5 text-text-secondary" title={formatDate(anomaly.detected_at)}>{relativeTime(anomaly.detected_at, status?.virtual_clock)}</td>
                      <td className="px-3 py-1.5"><div className="flex gap-1"><Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => void toggleAnomaly(anomaly)}>{expandedAnomalyId === anomaly.anomaly_id ? "Hide" : "Why?"}</Button>{relatedIncident ? <a className="rounded border border-border-strong px-2 py-1 text-xs font-semibold text-accent-cyan" href={`/incidents/${relatedIncident.incident_id}`}>Open incident</a> : null}</div></td>
                    </tr>,
                    expandedAnomalyId === anomaly.anomaly_id ? (
                      <tr key={`${anomaly.anomaly_id}-details`} className="border-t border-border-subtle bg-surface-soft"><td colSpan={7} className="px-3 py-3"><div className="grid gap-4 lg:grid-cols-2"><div><p className="font-semibold text-text-primary">Why the detector fired</p><p className="mt-1 text-text-secondary">{anomaly.explanation}</p><p className="font-data mt-2 text-xs text-text-muted">Detector: {anomaly.detector_id} · Event: {anomaly.event_id} · {formatDate(anomaly.detected_at)}</p></div><div><p className="font-semibold text-text-primary">Raw event payload</p>{rawEvent ? <pre className="font-data mt-1 max-h-48 overflow-auto rounded bg-slate-950 p-3 text-xs text-text-secondary">{JSON.stringify(rawEvent.raw_payload, null, 2)}</pre> : <p className="mt-1 text-text-muted">Loading raw event…</p>}</div></div></td></tr>
                    ) : null,
                  ];
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card as="section" data-testid={TEST_IDS.incidentList} className="order-2 border-l-2 border-l-accent-red p-5">
        <header><h2 className="text-lg font-semibold text-text-primary">Active incidents</h2><p className="text-sm text-text-secondary">Current immutable RCA snapshots requiring operator attention.</p></header>
        {incidents.length === 0 ? (
          <div className="mt-4"><EmptyState message={scenarioTriggered ? "Scenario completed without a published incident." : status?.scenario_state === "baseline_complete" ? "Baseline complete; choose and trigger a scenario." : "No current-run incident. Reset and run the baseline to begin."} /></div>
        ) : (
          <div className="mt-3 divide-y divide-border-subtle">{incidents.map((incident) => <a key={incident.incident_id} data-testid={incidentRowTestId(incident.incident_id)} aria-label={`Open incident ${incident.title}`} href={`/incidents/${incident.incident_id}`} className="group block border-l-2 border-l-accent-red px-4 py-3 hover:bg-surface-strong"><div className="flex items-center justify-between gap-3"><div><p className="font-semibold text-text-primary group-hover:text-accent-cyan">{incident.title}</p><p className="font-data mt-1 text-xs text-text-secondary">{incident.affected_entity_ids.join(", ")}</p></div><Badge variant={severityBadgeVariant(incident.severity)}>{severityLabel(incident.severity)}</Badge></div><div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-text-secondary"><p className="font-data">Start: {formatDate(incident.started_at)}</p><Badge variant={incidentStatusVariant(incident.status)}>{incident.status}</Badge></div></a>)}</div>
        )}
      </Card>
    </main>
  );
}
