import { useEffect, useMemo, useState } from "react";

import type { components } from "../contracts/openapi";
import { apiClient } from "../api/client";
import investigationFixture from "../test-fixtures/golden-investigation-response.json";
import {
  TEST_IDS,
  incidentRowTestId,
  sourceHealthTestId,
} from "../test-fixtures/testid-manifest";

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

function badgeClass(severity: "low" | "medium" | "high" | "critical") {
  switch (severity) {
    case "low":
      return "bg-emerald-100 text-emerald-800";
    case "medium":
      return "bg-amber-100 text-amber-900";
    case "high":
      return "bg-orange-100 text-orange-900";
    case "critical":
      return "bg-red-100 text-red-900";
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

  return (
    <main className="mx-auto max-w-6xl space-y-8 p-8">
      <header>
        <p className="text-sm font-semibold uppercase tracking-widest text-red-600">
          Operations
        </p>
        <h1 className="text-3xl font-bold">Network Anomaly RCA</h1>
        <p className="mt-2 text-slate-600">
          Phase 1 overview with source health, simulator controls, anomalies,
          and incident navigation.
        </p>
      </header>
      {apiError ? (
        <div
          role="alert"
          className="rounded-3xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900"
        >
          <strong className="font-semibold">Error:</strong> {apiError}
        </div>
      ) : null}
      {hasQuarantine ? (
        <div
          role="status"
          className="rounded-3xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900"
        >
          <span className="mr-2">⚠️</span>
          Quarantine warning: at least one source has quarantined records.
        </div>
      ) : null}

      <section className="grid gap-4 xl:grid-cols-[2fr_1fr]">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {health.map((source) => (
            <article
              key={source.id}
              className="rounded-2xl border bg-white p-5 shadow-sm"
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-sm font-semibold text-slate-900">
                    {source.title}
                  </p>
                  <p className="text-xs text-slate-500">{source.source}</p>
                </div>
                <span
                  data-testid={sourceHealthTestId(source.id)}
                  className={`rounded-full px-3 py-1 text-xs font-semibold ${
                    source.status === "ready"
                      ? "bg-emerald-100 text-emerald-900"
                      : "bg-red-100 text-red-900"
                  }`}
                >
                  {source.status}
                </span>
              </div>
              <div className="mt-4 space-y-2 text-sm text-slate-700">
                <p>Last ingest: {formatDate(source.ingestAt)}</p>
                <p>Accepted: {source.accepted}</p>
                <p>Collapsed: {source.collapsed}</p>
                <p>Quarantined: {source.quarantined}</p>
              </div>
            </article>
          ))}
        </div>

        <div className="space-y-4 rounded-2xl border bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold">Simulator Controls</h2>
              <p className="text-sm text-slate-500">
                Start, stop, reset, or trigger a scenario. Buttons are
                idempotent and disabled while transitioning.
              </p>
            </div>
            <div className="rounded-full bg-slate-100 px-3 py-1 text-sm font-medium text-slate-700">
              {formatClock(clock)}
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <button
              data-testid={TEST_IDS.simulatorStart}
              disabled={transitioning}
              aria-label="Start simulator"
              onClick={() => handleSimulatorAction("start")}
              className="rounded-xl bg-slate-900 px-4 py-3 text-sm font-semibold text-white transition disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              Start
            </button>
            <button
              data-testid={TEST_IDS.simulatorStop}
              disabled={transitioning}
              aria-label="Stop simulator"
              onClick={() => handleSimulatorAction("stop")}
              className="rounded-xl bg-slate-700 px-4 py-3 text-sm font-semibold text-white transition disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              Stop
            </button>
            <button
              data-testid={TEST_IDS.simulatorReset}
              disabled={transitioning}
              aria-label="Reset simulator"
              onClick={() => handleSimulatorAction("reset")}
              className="rounded-xl bg-slate-500 px-4 py-3 text-sm font-semibold text-white transition disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              Reset
            </button>
            <button
              data-testid={TEST_IDS.scenarioTrigger}
              disabled={transitioning}
              aria-label="Trigger scenario"
              onClick={() => triggerScenario(preferredScenario)}
              className="rounded-xl bg-sky-600 px-4 py-3 text-sm font-semibold text-white transition disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              Trigger scenario
            </button>
          </div>

          <label className="block text-sm font-medium text-slate-700">
            Scenario
            <select
              data-testid="scenario-select"
              value={preferredScenario}
              onChange={(event) => setPreferredScenario(event.target.value)}
              disabled={transitioning}
              aria-label="Choose scenario"
              className="mt-2 block w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-100"
            >
              {scenarios.map((scenario) => (
                <option key={scenario.id} value={scenario.id}>
                  {scenario.title}
                </option>
              ))}
            </select>
          </label>

          <p className="rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-700">
            <span aria-hidden="true">📡</span> State:{" "}
            <span className="font-semibold">{statusMessage}</span>
          </p>
          <p className="text-sm text-slate-500">
            {scenarioTriggered
              ? "Scenario active and the baseline has been replaced."
              : "Baseline running; no incident has been triggered yet."}
          </p>
        </div>
      </section>

      <section className="rounded-2xl border bg-white p-5 shadow-sm">
        <header className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold">Recent Anomalies</h2>
            <p className="text-sm text-slate-500">
              Last 20 records update automatically as the system polls.
            </p>
          </div>
          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-slate-600">
            Polling
          </span>
        </header>

        <div className="mt-4 overflow-hidden rounded-xl border">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                <th className="px-4 py-3">Entity</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Score</th>
                <th className="px-4 py-3">Detector</th>
                <th className="px-4 py-3">Time</th>
              </tr>
            </thead>
            <tbody>
              {anomalies.slice(0, 20).map((anomaly) => (
                <tr
                  key={anomaly.anomalyId}
                  className="border-t border-slate-100 hover:bg-slate-50"
                >
                  <td className="px-4 py-3 font-medium text-slate-900">
                    {anomaly.entity}
                  </td>
                  <td className="px-4 py-3 text-slate-700">{anomaly.type}</td>
                  <td className="px-4 py-3 text-slate-700">
                    {anomaly.score.toFixed(1)}
                  </td>
                  <td className="px-4 py-3 text-slate-700">
                    {anomaly.detectorId}
                  </td>
                  <td className="px-4 py-3 text-slate-700">
                    {formatDate(anomaly.timestamp)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section
        data-testid={TEST_IDS.incidentList}
        className="rounded-2xl border bg-white p-5 shadow-sm"
      >
        <header className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold">Incident List</h2>
            <p className="text-sm text-slate-500">
              Select an incident to investigate the RCA snapshot.
            </p>
          </div>
          <span className={badgeClass(incidentRow.severity)}>
            {incidentRow.status}
          </span>
        </header>

        <div className="mt-4 divide-y divide-slate-100">
          <a
            data-testid={incidentRowTestId(incidentRow.incidentId)}
            href={`/incidents/${incidentRow.incidentId}`}
            className="block space-y-3 rounded-2xl p-4 transition hover:bg-slate-50"
          >
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-lg font-semibold text-slate-900">
                  {incidentRow.title}
                </p>
                <p className="mt-1 text-sm text-slate-600">
                  {incidentRow.affectedEntities.join(", ")}
                </p>
              </div>
              <span className="rounded-full bg-sky-100 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-sky-700">
                {incidentRow.severity}
              </span>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <p className="text-sm text-slate-600">
                Start: {formatDate(incidentRow.startTime)}
              </p>
              <p className="text-sm text-slate-600">
                Status: {incidentRow.status}
              </p>
            </div>
          </a>
        </div>
      </section>
    </main>
  );
}
