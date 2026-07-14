import { useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import { usePolling } from "../hooks/usePolling";
import {
  CartesianGrid,
  ComposedChart,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { components } from "../contracts/openapi";
import { apiClient } from "../api/client";
import investigationFixture from "../test-fixtures/golden-investigation-response.json";
import {
  TEST_IDS,
  hypothesisRowTestId,
} from "../test-fixtures/testid-manifest";

type InvestigationResponse = components["schemas"]["InvestigationResponse"];

type InvestigationPageProps = {
  incidentId: string;
};

type TimelinePoint = {
  x: number;
  y: number;
  event: components["schemas"]["CanonicalEvent"];
  attachment_score: number;
  attachment_reasons: string[];
  modality: components["schemas"]["Modality"];
  attached: boolean;
};

const laneOrder: components["schemas"]["Modality"][] = [
  "metric",
  "log",
  "alert",
  "config_change",
];
const laneLabels: Record<components["schemas"]["Modality"], string> = {
  metric: "Metric",
  log: "Log",
  alert: "Alert",
  config_change: "Config Change",
};
const laneColor: Record<components["schemas"]["Modality"], string> = {
  metric: "#0ea5e9",
  log: "#22c55e",
  alert: "#f97316",
  config_change: "#8b5cf6",
};

function createUuid() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

function formatTimestamp(value: number) {
  return new Date(value).toLocaleTimeString("en-US", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
  });
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

function determineBadgeClass(status: string) {
  switch (status) {
    case "open":
      return "bg-amber-100 text-amber-900";
    case "investigating":
      return "bg-sky-100 text-sky-900";
    case "resolved":
      return "bg-emerald-100 text-emerald-900";
    case "rejected":
      return "bg-red-100 text-red-900";
    default:
      return "bg-slate-100 text-slate-700";
  }
}

function eventColor(point: TimelinePoint) {
  if (!point.attached) {
    return "#cbd5e1";
  }
  return laneColor[point.modality];
}

function kindToModality(
  kind: components["schemas"]["EvidenceKind"],
): components["schemas"]["Modality"] {
  switch (kind) {
    case "observed":
      return "log";
    case "correlated":
      return "alert";
    case "conflicting":
      return "metric";
    case "missing":
      return "config_change";
    default:
      return "log";
  }
}

const defaultInvestigation =
  investigationFixture as unknown as InvestigationResponse;

export function InvestigationPage({ incidentId }: InvestigationPageProps) {
  const [investigation, setInvestigation] =
    useState<InvestigationResponse | null>(defaultInvestigation);
  const [auditTrail, setAuditTrail] = useState<
    components["schemas"]["AuditRecord"][]
  >([]);
  const [selectedEvent, setSelectedEvent] = useState<
    components["schemas"]["CanonicalEvent"] | null
  >(null);
  const [reviewStatus, setReviewStatus] = useState<Record<string, string>>({});
  const [busyHypothesis, setBusyHypothesis] = useState<Record<string, boolean>>(
    {},
  );
  const [banner, setBanner] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [auditFilter, setAuditFilter] = useState("");
  const latestRevisionRef = useRef<number | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  async function loadInvestigation() {
    try {
      setIsRefreshing(true);
      const response = await apiClient.get<InvestigationResponse>(
        `/incidents/${incidentId}/investigation`,
      );
      const revision = response.data.analysis_run.revision;
      if (
        latestRevisionRef.current !== null &&
        revision <= latestRevisionRef.current
      ) {
        return;
      }
      if (latestRevisionRef.current !== null) {
        setBanner("Analysis updated; now displaying the latest snapshot.");
      }
      latestRevisionRef.current = revision;
      setInvestigation(response.data);
      setApiError(null);
    } catch (error: any) {
      const code = error?.response?.data?.code as string | undefined;
      setApiError(
        code
          ? `${code}: Unable to load investigation snapshot`
          : "Unable to load investigation snapshot",
      );
    } finally {
      setIsRefreshing(false);
    }
  }

  useEffect(() => {
    void loadInvestigation();
  }, [incidentId]);

  usePolling(loadInvestigation, 1500);

  useEffect(() => {
    async function loadAudit() {
      if (!investigation) {
        return;
      }
      try {
        const response = await apiClient.get<
          components["schemas"]["AuditRecord"][]
        >(`/incidents/${incidentId}/audit`);
        setAuditTrail(response.data);
      } catch {
        // keep existing audit trail if unavailable
      }
    }

    void loadAudit();
  }, [incidentId, investigation]);

  const evidenceByHypothesis = useMemo(
    () => investigation?.evidence_by_hypothesis ?? {},
    [investigation],
  );

  const timelinePoints = useMemo<TimelinePoint[]>(() => {
    if (!investigation) {
      return [];
    }

    return investigation.timeline.map((item) => ({
      x: new Date(item.event.timestamp).getTime(),
      y: laneOrder.indexOf(item.event.modality),
      event: item.event,
      attachment_score: item.attachment_score,
      attachment_reasons: item.attachment_reasons,
      modality: item.event.modality,
      attached: item.attachment_decision === "attached",
    }));
  }, [investigation]);

  const groupedEvidence = useMemo(() => {
    const grouped: Record<
      components["schemas"]["EvidenceKind"],
      components["schemas"]["EvidenceItem"][]
    > = {
      observed: [],
      correlated: [],
      conflicting: [],
      missing: [],
    };

    Object.values(evidenceByHypothesis)
      .flat()
      .forEach((item) => {
        grouped[item.kind].push(item);
      });

    return grouped;
  }, [evidenceByHypothesis]);

  function openEventModal(event: components["schemas"]["CanonicalEvent"]) {
    setSelectedEvent(event);
  }

  function closeEventModal() {
    setSelectedEvent(null);
  }

  async function postReview(
    hypothesisId: string,
    decision: "confirmed" | "rejected" | "evidence_requested",
    requestedEvidenceId?: string,
  ) {
    setBanner(null);
    setBusyHypothesis((current) => ({ ...current, [hypothesisId]: true }));

    const body: Record<string, unknown> = {
      analysis_run_id: investigation?.analysis_run_id,
      client_action_id: createUuid(),
      comment:
        decision === "confirmed"
          ? "Confirmed root cause"
          : decision === "rejected"
            ? "Hypothesis rejected"
            : "Evidence requested",
      decision,
      hypothesis_id: hypothesisId,
      reviewer: "operator",
    };

    if (requestedEvidenceId) {
      body.requested_evidence_id = requestedEvidenceId;
    }

    try {
      await apiClient.post(`/incidents/${incidentId}/review`, body);
      setReviewStatus((current) => ({ ...current, [hypothesisId]: decision }));
      if (decision === "confirmed") {
        setBanner("Confirmed root cause");
      }
    } catch (error: any) {
      if (error?.response?.status === 409) {
        const code = error.response.data?.code;
        if (code === "STALE_ANALYSIS") {
          setBanner("Analysis updated, refresh the page");
        } else if (code === "REVIEW_CONFLICT") {
          setBanner("Decision already recorded");
        } else {
          setBanner("Review action failed");
        }
      } else {
        setBanner("Review action failed");
      }
    } finally {
      setBusyHypothesis((current) => ({ ...current, [hypothesisId]: false }));
    }
  }

  if (!investigation) {
    return <div className="p-8">Loading incident investigation...</div>;
  }

  const filteredAuditTrail = auditTrail.filter((record) =>
    `${record.actor_type} ${record.action} ${record.object_type} ${record.object_id}`
      .toLowerCase()
      .includes(auditFilter.toLowerCase()),
  );

  return (
    <main
      data-testid={TEST_IDS.investigationPanel}
      className="mx-auto max-w-7xl space-y-8 p-8"
    >
      <header className="space-y-3 rounded-3xl border bg-white p-6 shadow-sm">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div>
            <p className="text-sm text-slate-500">
              Analysis run {investigation.analysis_run_id}
            </p>
            <h1 className="text-3xl font-bold">
              {investigation.incident.title}
            </h1>
            <p className="mt-2 text-slate-600">
              Current incident status:{" "}
              <span className="font-semibold">
                {investigation.incident.status}
              </span>
            </p>
          </div>
          <div className="rounded-2xl bg-slate-100 px-4 py-3 text-sm text-slate-700">
            Affected entities:{" "}
            {Array.from(
              new Set(
                investigation.hypotheses.map((h) => h.candidate_entity_id),
              ),
            ).join(", ")}
          </div>
        </div>
        {banner ? (
          <div
            role="status"
            className="rounded-2xl bg-amber-100 px-4 py-3 text-sm font-semibold text-amber-900"
            data-testid={TEST_IDS.staleAnalysisBanner}
          >
            <span aria-hidden="true">ℹ️</span> {banner}
          </div>
        ) : null}
        {apiError ? (
          <div
            role="alert"
            className="rounded-2xl bg-red-50 px-4 py-3 text-sm font-semibold text-red-900"
          >
            <span aria-hidden="true">❌</span> {apiError}
          </div>
        ) : null}
      </header>

      <section className="grid gap-6 xl:grid-cols-[2fr_1fr]">
        <div className="space-y-6">
          <article className="rounded-3xl border bg-white p-6 shadow-sm">
            <h2 className="text-xl font-semibold">Incident Timeline</h2>
            <p className="mt-2 text-sm text-slate-500">
              One aligned time axis with four lanes. Click an event to inspect
              the raw record.
            </p>
            <div
              className="mt-6 h-[420px]"
              data-testid={TEST_IDS.timelinePanel}
            >
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={timelinePoints}>
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke="#e2e8f0"
                    vertical={false}
                  />
                  <XAxis
                    dataKey="x"
                    type="number"
                    scale="time"
                    domain={["dataMin", "dataMax"]}
                    tickFormatter={formatTimestamp}
                    tick={{ fill: "#475569", fontSize: 12 }}
                  />
                  <YAxis
                    dataKey="y"
                    type="number"
                    domain={[0, laneOrder.length - 1]}
                    tickFormatter={(value) =>
                      laneLabels[value as components["schemas"]["Modality"]]
                    }
                    ticks={laneOrder.map((_, index) => index)}
                    tick={{ fill: "#475569", fontSize: 12 }}
                  />
                  <Tooltip
                    cursor={{ stroke: "#64748b", strokeWidth: 1 }}
                    formatter={(_, name) => [name, "event"]}
                    labelFormatter={(value) =>
                      `Time: ${formatTimestamp(Number(value))}`
                    }
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) {
                        return null;
                      }
                      const point = payload[0].payload as TimelinePoint;
                      return (
                        <div className="rounded-2xl border bg-white p-3 shadow-lg">
                          <p className="text-sm font-semibold text-slate-900">
                            {laneLabels[point.modality]}
                          </p>
                          <p className="mt-1 text-sm text-slate-600">
                            {point.event.event_type}
                          </p>
                          <p className="mt-1 text-xs text-slate-500">
                            Score: {point.attachment_score}
                          </p>
                        </div>
                      );
                    }}
                  />
                  <Scatter
                    name="events"
                    data={timelinePoints}
                    dataKey="x"
                    fill="#0ea5e9"
                    shape={(props) => {
                      const { cx, cy, payload } = props as any;
                      if (cx == null || cy == null) {
                        return null;
                      }
                      const point = payload as TimelinePoint;
                      return (
                        <circle
                          cx={cx}
                          cy={cy}
                          r={point.attached ? 8 : 6}
                          data-attached={String(point.attached)}
                          data-testid="timeline-event"
                          fill={eventColor(point)}
                          stroke={point.attached ? "#0f172a" : "#94a3b8"}
                          strokeWidth={point.attached ? 2 : 1}
                          style={{ cursor: "pointer" }}
                          onClick={() => openEventModal(point.event)}
                        />
                      );
                    }}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </article>

          <article className="rounded-3xl border bg-white p-6 shadow-sm">
            <h2 className="text-xl font-semibold">Topology Impact Graph</h2>
            <p className="mt-2 text-sm text-slate-500">
              Topology is rendered from the single investigation snapshot; edges
              show relation_type and node state.
            </p>
            <div
              className="mt-6 h-[420px] rounded-3xl border border-slate-200 bg-slate-50"
              data-testid={TEST_IDS.topologyGraph}
            >
              <ReactFlow
                nodes={investigation.topology.nodes.map((node, index) => ({
                  id: node.id,
                  position: {
                    x: (index % 4) * 220 + 30,
                    y: Math.floor(index / 4) * 140 + 30,
                  },
                  data: { label: `${node.name}` },
                  style: {
                    backgroundColor:
                      node.state === "suspected_root"
                        ? "#f97316"
                        : node.state === "primary_affected"
                          ? "#ef4444"
                          : node.state === "impact_path"
                            ? "#22c55e"
                            : node.state === "blast_radius"
                              ? "#6366f1"
                              : "#64748b",
                    color: "white",
                    border: "2px solid rgba(255,255,255,0.8)",
                    padding: 10,
                    width: 180,
                    borderRadius: 16,
                  },
                }))}
                edges={investigation.topology.edges.map((edge, index) => ({
                  id: `${edge.source}-${edge.target}-${edge.relation_type}-${index}`,
                  source: edge.source,
                  target: edge.target,
                  type: "smoothstep",
                  label: edge.relation_type,
                  labelBgPadding: [6, 4],
                  labelBgBorderRadius: 4,
                  labelBgStyle: { fill: "#f8fafc", stroke: "#cbd5e1" },
                  animated: false,
                }))}
                fitView
              >
                <Background gap={16} />
                <Controls />
              </ReactFlow>
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div className="rounded-2xl bg-slate-50 p-4 text-sm text-slate-700">
                <p className="font-semibold">Node states</p>
                <ul className="mt-3 space-y-2">
                  <li className="flex items-center gap-2">
                    <span className="h-3 w-3 rounded-full bg-orange-500"></span>{" "}
                    suspected_root
                  </li>
                  <li className="flex items-center gap-2">
                    <span className="h-3 w-3 rounded-full bg-red-600"></span>{" "}
                    primary_affected
                  </li>
                  <li className="flex items-center gap-2">
                    <span className="h-3 w-3 rounded-full bg-emerald-500"></span>{" "}
                    impact_path
                  </li>
                  <li className="flex items-center gap-2">
                    <span className="h-3 w-3 rounded-full bg-indigo-500"></span>{" "}
                    blast_radius
                  </li>
                </ul>
              </div>
              <div className="rounded-2xl bg-slate-50 p-4 text-sm text-slate-700">
                <p className="font-semibold">Edge labels</p>
                <ul className="mt-3 space-y-2">
                  <li>
                    <strong>depends_on</strong> — static relationship between
                    nodes
                  </li>
                  <li>
                    <strong>sends_traffic_to</strong> — traffic direction used
                    by active hypothesis
                  </li>
                </ul>
              </div>
            </div>
          </article>
        </div>

        <aside className="space-y-6">
          <article className="rounded-3xl border bg-white p-6 shadow-sm">
            <h2 className="text-xl font-semibold">Ranked Hypotheses</h2>
            <div className="mt-4 space-y-4">
              {investigation.hypotheses.map((hypothesis) => {
                const evidenceItems =
                  evidenceByHypothesis[hypothesis.hypothesis_id] ?? [];
                const missingEvidence = evidenceItems.filter(
                  (item) => item.kind === "missing",
                );
                const confirmed =
                  reviewStatus[hypothesis.hypothesis_id] === "confirmed";
                return (
                  <article
                    key={hypothesis.hypothesis_id}
                    data-testid={hypothesisRowTestId(hypothesis.hypothesis_id)}
                    className="rounded-3xl border border-slate-200 p-4"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold uppercase tracking-wide text-slate-500">
                          Rank {hypothesis.rank}
                        </p>
                        <p className="mt-2 text-lg font-semibold text-slate-900">
                          {confirmed
                            ? "Confirmed root cause"
                            : hypothesis.candidate_entity_id}
                        </p>
                        {!confirmed ? (
                          <p className="text-sm text-slate-600">
                            {hypothesis.hypothesis_type}
                          </p>
                        ) : null}
                      </div>
                      <div className="rounded-3xl bg-slate-100 px-4 py-2 text-sm font-semibold text-slate-800">
                        Evidence score {Math.round(hypothesis.evidence_score)}
                      </div>
                    </div>
                    <div className="mt-4 rounded-3xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
                      {hypothesis.evidence_coverage.available}/
                      {hypothesis.evidence_coverage.expected} expected evidence
                      requirements available
                    </div>
                    <details className="mt-4 rounded-3xl border border-slate-200 bg-white p-4">
                      <summary className="cursor-pointer text-sm font-semibold text-slate-900">
                        Factor breakdown
                      </summary>
                      <div className="mt-3 grid gap-3 sm:grid-cols-2">
                        {Object.entries(hypothesis.factor_scores).map(
                          ([factor, score]) => (
                            <div
                              key={factor}
                              className="rounded-2xl bg-slate-50 p-3 text-sm"
                            >
                              <p className="font-semibold text-slate-800">
                                {factor}
                              </p>
                              <p className="mt-1 text-slate-600">
                                {Number(score).toFixed(2)}
                              </p>
                            </div>
                          ),
                        )}
                      </div>
                    </details>
                    <div className="mt-4 flex flex-wrap gap-3">
                      <button
                        data-testid={TEST_IDS.hypothesisConfirm}
                        aria-label="Confirm hypothesis"
                        className="rounded-2xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                        disabled={busyHypothesis[hypothesis.hypothesis_id]}
                        onClick={() =>
                          postReview(hypothesis.hypothesis_id, "confirmed")
                        }
                      >
                        Confirm
                      </button>
                      <button
                        data-testid={TEST_IDS.hypothesisReject}
                        aria-label="Reject hypothesis"
                        className="rounded-2xl bg-red-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
                        disabled={busyHypothesis[hypothesis.hypothesis_id]}
                        onClick={() =>
                          postReview(hypothesis.hypothesis_id, "rejected")
                        }
                      >
                        Reject
                      </button>
                      <button
                        data-testid={TEST_IDS.evidenceRequest}
                        aria-label="Request evidence"
                        className="rounded-2xl bg-amber-500 px-4 py-2 text-sm font-semibold text-slate-900 disabled:opacity-60"
                        disabled={
                          busyHypothesis[hypothesis.hypothesis_id] ||
                          missingEvidence.length === 0
                        }
                        onClick={() =>
                          postReview(
                            hypothesis.hypothesis_id,
                            "evidence_requested",
                            missingEvidence[0]?.evidence_id,
                          )
                        }
                      >
                        Request evidence
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          </article>

          <article
            className="rounded-3xl border bg-white p-6 shadow-sm"
            data-testid={TEST_IDS.evidencePanel}
          >
            <h2 className="text-xl font-semibold">Evidence Explorer</h2>
            <p className="mt-2 text-sm text-slate-500">
              Verified observed facts, correlated signals, conflicting evidence,
              and missing evidence.
            </p>
            <div className="mt-4 space-y-3">
              {(
                [
                  "observed",
                  "correlated",
                  "conflicting",
                  "missing",
                ] as components["schemas"]["EvidenceKind"][]
              ).map((kind) => (
                <details
                  key={kind}
                  className="rounded-3xl border border-slate-200 bg-slate-50 p-4"
                >
                  <summary className="cursor-pointer font-semibold text-slate-900">
                    {kind === "observed"
                      ? "Verified observed facts"
                      : kind === "correlated"
                        ? "Correlated signals"
                        : kind === "conflicting"
                          ? "Conflicting evidence"
                          : "Missing evidence"}
                  </summary>
                  <div className="mt-3 space-y-3">
                    {groupedEvidence[kind].length === 0 ? (
                      <p className="text-sm text-slate-500">
                        No items in this category.
                      </p>
                    ) : (
                      groupedEvidence[kind].map((item) => (
                        <button
                          key={item.evidence_id}
                          className={`w-full rounded-2xl border p-4 text-left text-sm transition ${
                            kind === "conflicting"
                              ? "border-amber-300 bg-amber-50 text-amber-900"
                              : kind === "missing"
                                ? "border-slate-300 bg-slate-50 text-slate-900"
                                : "border-slate-200 bg-white text-slate-900"
                          }`}
                          onClick={() => {
                            const canonicalEvent = {
                              entity_id:
                                item.source_event_id ?? item.evidence_id,
                              event_id:
                                item.source_event_id ?? item.evidence_id,
                              event_type: item.reason_code,
                              ingested_at: item.created_at,
                              modality: kindToModality(kind),
                              schema_version: "1.0",
                              severity: 0,
                              source: "evidence",
                              timestamp: item.created_at,
                              quality_flags: [],
                              raw_payload: {},
                            } as components["schemas"]["CanonicalEvent"];

                            openEventModal(canonicalEvent);
                          }}
                        >
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <p className="font-semibold">{item.statement}</p>
                              {kind === "observed" ? (
                                <p className="mt-1 text-xs text-slate-500">
                                  Confirms the record and value were observed;
                                  does not confirm causation
                                </p>
                              ) : null}
                            </div>
                            <span className="text-xs font-semibold uppercase tracking-wide">
                              {kind === "conflicting"
                                ? "Conflicting"
                                : kind === "missing"
                                  ? "Missing"
                                  : kind === "correlated"
                                    ? "Correlated"
                                    : "Observed"}
                            </span>
                          </div>
                        </button>
                      ))
                    )}
                  </div>
                </details>
              ))}
            </div>
          </article>

          <article className="rounded-3xl border bg-white p-6 shadow-sm">
            <h2 className="text-xl font-semibold">Explanation summary</h2>
            <p className="mt-2 text-sm text-slate-500">
              Diagnostic summary from the current investigation snapshot.
            </p>
            <div className="mt-4 rounded-3xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
              <p className="font-semibold text-slate-900">
                {investigation.explanation.summary}
              </p>
              <p className="mt-2">
                Generator:{" "}
                <span className="font-semibold">
                  {investigation.explanation.generator}
                </span>
              </p>
              <p className="mt-2 text-slate-600">
                {investigation.explanation.claims.length} supporting claims
              </p>
            </div>
          </article>

          <article className="rounded-3xl border bg-white p-6 shadow-sm">
            <h2 className="text-xl font-semibold">Catalogue Recommendations</h2>
            <p className="mt-2 text-sm text-slate-500">
              Recommendations are safe suggestions and are not executed
              automatically.
            </p>
            <div className="mt-4 space-y-4">
              {investigation.hypotheses.flatMap((hypothesis) => {
                const recommendations =
                  investigation.recommendations_by_hypothesis[
                    hypothesis.hypothesis_id
                  ] ?? [];
                return recommendations.map((recommendation) => (
                  <div
                    key={recommendation.recommendation_id}
                    className="rounded-3xl border border-slate-200 bg-slate-50 p-4"
                  >
                    <p className="font-semibold text-slate-900">
                      Catalogue recommendation — not executed
                    </p>
                    <p className="mt-2 text-sm text-slate-700">
                      {recommendation.title}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-600">
                      <span>step_id: {recommendation.step_id}</span>
                      <span>risk_level: {recommendation.risk_level}</span>
                      <span>
                        requires_human_approval:{" "}
                        {recommendation.requires_human_approval ? "yes" : "no"}
                      </span>
                    </div>
                  </div>
                ));
              })}
            </div>
          </article>

          <article className="rounded-3xl border bg-white p-6 shadow-sm">
            <h2 className="text-xl font-semibold">Audit Trail</h2>
            <p className="mt-2 text-sm text-slate-500">
              Append-only table showing action history for this incident.
            </p>
            <div className="mt-4" data-testid={TEST_IDS.auditTrailPanel} />
            <label className="mt-4 block text-sm font-medium text-slate-700">
              Filter audit entries
              <input
                value={auditFilter}
                onChange={(event) => setAuditFilter(event.target.value)}
                className="mt-2 block w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-100"
                placeholder="Type actor, action, or object"
              />
            </label>
            <div className="mt-4 overflow-hidden rounded-3xl border">
              <table className="min-w-full text-left text-sm">
                <thead className="bg-slate-100 text-slate-600">
                  <tr>
                    <th className="px-4 py-3">Timestamp</th>
                    <th className="px-4 py-3">Actor</th>
                    <th className="px-4 py-3">Action</th>
                    <th className="px-4 py-3">Object</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredAuditTrail.map((record) => (
                    <tr
                      key={record.audit_id}
                      className="border-t border-slate-100"
                    >
                      <td className="px-4 py-3 text-slate-700">
                        {formatDate(record.timestamp)}
                      </td>
                      <td className="px-4 py-3 text-slate-700">
                        {record.actor_type}
                      </td>
                      <td className="px-4 py-3 text-slate-700">
                        {record.action}
                      </td>
                      <td className="px-4 py-3 text-slate-700">
                        {record.object_type} {record.object_id}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </article>
        </aside>
      </section>

      {selectedEvent ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
          <div className="max-h-[90vh] w-full max-w-3xl overflow-auto rounded-3xl bg-white p-6 shadow-2xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-xl font-semibold">Raw CanonicalEvent</h2>
                <p className="mt-1 text-sm text-slate-500">
                  Attachment score and reasons accompany the raw event.
                </p>
              </div>
              <button
                onClick={closeEventModal}
                className="rounded-full bg-slate-100 px-3 py-2 text-slate-700"
              >
                Close
              </button>
            </div>
            <div className="mt-6 space-y-3 rounded-3xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
              <pre className="whitespace-pre-wrap break-words text-xs">
                {JSON.stringify(selectedEvent, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
