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
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { components } from "../contracts/openapi";
import { apiClient } from "../api/client";
import investigationFixture from "../test-fixtures/golden-investigation-response.json";
import {
  TEST_IDS,
  evidenceRequestTestId,
  hypothesisConfirmTestId,
  hypothesisRejectTestId,
  hypothesisRowTestId,
} from "../test-fixtures/testid-manifest";
import { Card } from "../components/ui/Card";
import { Badge, type BadgeVariant } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { EvidenceScoreBar } from "../components/ui/EvidenceScoreBar";
import { EmptyState } from "../components/ui/EmptyState";
import { Tooltip as UiTooltip } from "../components/ui/Tooltip";
import { PageSkeleton } from "../components/ui/Skeleton";
import {
  AlertTriangleIcon,
  CheckIcon,
  ClipboardListIcon,
  ClockIcon,
  HelpCircleIcon,
  InfoIcon,
  LinkIcon,
  NetworkIcon,
  SearchIcon,
  SparklesIcon,
  XIcon,
} from "../components/icons";

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
  metric: "#22d3ee",
  log: "#34d399",
  alert: "#fbbf24",
  config_change: "#a78bfa",
};

const CHART_COLORS = {
  gridStroke: "rgba(148, 163, 184, 0.14)",
  axisTick: "#94a3b8",
  excludedDot: "#475569",
};

const EDGE_LABEL_STYLE = { fill: "#e2e8f0", stroke: "#1e293b" };

const NODE_BASE_CLASS =
  "w-[180px] rounded-2xl border-2 px-3 py-2.5 text-center text-sm font-semibold text-white shadow-glass";

const NODE_STATE_CLASS: Record<string, string> = {
  suspected_root:
    "bg-gradient-to-br from-accent-amber to-orange-500 border-accent-amber/60",
  primary_affected:
    "bg-gradient-to-br from-accent-red to-accent-red-strong border-accent-red/60",
  impact_path:
    "bg-gradient-to-br from-accent-emerald to-accent-emerald-strong border-accent-emerald/60",
  blast_radius:
    "bg-gradient-to-br from-accent-purple to-accent-purple-strong border-accent-purple/60",
};
const NODE_STATE_FALLBACK_CLASS = "bg-white/10 border-white/20";

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

function statusBadgeVariant(status: string): BadgeVariant {
  switch (status) {
    case "open":
      return "warning";
    case "investigating":
      return "info";
    case "resolved":
      return "success";
    case "rejected":
      return "danger";
    default:
      return "neutral";
  }
}

function eventColor(point: TimelinePoint) {
  if (!point.attached) {
    return CHART_COLORS.excludedDot;
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

const EVIDENCE_KIND_LABEL: Record<
  components["schemas"]["EvidenceKind"],
  string
> = {
  observed: "Verified observed facts",
  correlated: "Correlated signals",
  conflicting: "Conflicting evidence",
  missing: "Missing evidence",
};

const EVIDENCE_KIND_ICON: Record<
  components["schemas"]["EvidenceKind"],
  typeof CheckIcon
> = {
  observed: CheckIcon,
  correlated: LinkIcon,
  conflicting: AlertTriangleIcon,
  missing: HelpCircleIcon,
};

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
    return <PageSkeleton label="Loading incident investigation..." />;
  }

  const filteredAuditTrail = auditTrail.filter((record) =>
    `${record.actor_type} ${record.action} ${record.object_type} ${record.object_id}`
      .toLowerCase()
      .includes(auditFilter.toLowerCase()),
  );

  return (
    <main
      data-testid={TEST_IDS.investigationPanel}
      className="mx-auto max-w-7xl space-y-8 p-4 sm:p-6 lg:p-8"
    >
      <Card as="header" glow="none" className="animate-fade-in-up space-y-3 p-6">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <p className="flex items-center gap-1.5 text-sm text-text-secondary">
              <ClockIcon className="h-3.5 w-3.5" />
              Analysis run {investigation.analysis_run_id}
            </p>
            <h1 className="mt-1 break-words text-3xl font-extrabold tracking-tight text-text-primary">
              {investigation.incident.title}
            </h1>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Badge variant={statusBadgeVariant(investigation.incident.status)}>
                {investigation.incident.status}
              </Badge>
              <span className="text-sm text-text-secondary">
                Current incident status
              </span>
            </div>
          </div>
          <div className="glass-inset shrink-0 px-4 py-3 text-sm text-text-secondary md:max-w-xs">
            Affected entities:{" "}
            <span className="font-semibold text-text-primary">
              {Array.from(
                new Set(
                  investigation.hypotheses.map((h) => h.candidate_entity_id),
                ),
              ).join(", ")}
            </span>
          </div>
        </div>
        {banner ? (
          <div
            role="status"
            className="glass-panel flex items-center gap-2 border-accent-amber/30 bg-accent-amber/10 px-4 py-3 text-sm font-semibold text-accent-amber"
            data-testid={
              banner.includes("Analysis updated")
                ? TEST_IDS.staleAnalysisBanner
                : TEST_IDS.genericBanner
            }
          >
            <InfoIcon className="h-4 w-4 shrink-0" aria-hidden="true" /> {banner}
          </div>
        ) : null}
        {apiError ? (
          <div
            role="alert"
            className="glass-panel flex items-center gap-2 border-accent-red/30 bg-accent-red/10 px-4 py-3 text-sm font-semibold text-accent-red"
          >
            <AlertTriangleIcon className="h-4 w-4 shrink-0" aria-hidden="true" />{" "}
            {apiError}
          </div>
        ) : null}
      </Card>

      <section className="grid gap-6 xl:grid-cols-[2fr_1fr]">
        <div className="space-y-6">
          <Card interactive glow="cyan">
            <div className="flex items-center gap-2">
              <ClockIcon className="h-5 w-5 text-accent-cyan" />
              <h2 className="text-xl font-semibold text-text-primary">
                Incident Timeline
              </h2>
            </div>
            <p className="mt-2 text-sm text-text-secondary">
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
                    stroke={CHART_COLORS.gridStroke}
                    vertical={false}
                  />
                  <XAxis
                    dataKey="x"
                    type="number"
                    scale="time"
                    domain={["dataMin", "dataMax"]}
                    tickFormatter={formatTimestamp}
                    tick={{ fill: CHART_COLORS.axisTick, fontSize: 12 }}
                    stroke={CHART_COLORS.gridStroke}
                  />
                  <YAxis
                    dataKey="y"
                    type="number"
                    domain={[0, laneOrder.length - 1]}
                    tickFormatter={(value) =>
                      laneLabels[value as components["schemas"]["Modality"]]
                    }
                    ticks={laneOrder.map((_, index) => index)}
                    tick={{ fill: CHART_COLORS.axisTick, fontSize: 12 }}
                    stroke={CHART_COLORS.gridStroke}
                  />
                  <RechartsTooltip
                    cursor={{ stroke: "#38bdf8", strokeWidth: 1 }}
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
                        <div className="glass-panel px-3 py-2.5 text-sm">
                          <p className="font-semibold text-text-primary">
                            {laneLabels[point.modality]}
                          </p>
                          <p className="mt-1 text-text-secondary">
                            {point.event.event_type}
                          </p>
                          <p className="mt-1 text-xs text-text-muted">
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
                    fill="#22d3ee"
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
                          stroke={point.attached ? "#e2e8f0" : "#64748b"}
                          strokeWidth={point.attached ? 2 : 1}
                          className="cursor-pointer"
                          onClick={() => openEventModal(point.event)}
                        />
                      );
                    }}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <Card interactive glow="purple">
            <div className="flex items-center gap-2">
              <NetworkIcon className="h-5 w-5 text-accent-purple" />
              <h2 className="text-xl font-semibold text-text-primary">
                Topology Impact Graph
              </h2>
            </div>
            <p className="mt-2 text-sm text-text-secondary">
              Topology is rendered from the single investigation snapshot;
              edges show relation_type and node state.
            </p>
            <div
              className="glass-inset mt-6 h-[420px] overflow-hidden"
              data-testid={TEST_IDS.topologyGraph}
            >
              <ReactFlow
                className="react-flow-dark"
                nodes={investigation.topology.nodes.map((node, index) => ({
                  id: node.id,
                  position: {
                    x: (index % 4) * 220 + 30,
                    y: Math.floor(index / 4) * 140 + 30,
                  },
                  data: { label: `${node.name}` },
                  className: `${NODE_BASE_CLASS} ${
                    NODE_STATE_CLASS[String(node.state)] ??
                    NODE_STATE_FALLBACK_CLASS
                  }`,
                }))}
                edges={investigation.topology.edges.map((edge, index) => ({
                  id: `${edge.source}-${edge.target}-${edge.relation_type}-${index}`,
                  source: edge.source,
                  target: edge.target,
                  type: "smoothstep",
                  label: edge.relation_type,
                  labelBgPadding: [6, 4],
                  labelBgBorderRadius: 4,
                  labelBgStyle: EDGE_LABEL_STYLE,
                  animated: false,
                }))}
                fitView
              >
                <Background gap={16} />
                <Controls />
              </ReactFlow>
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div className="glass-inset p-4 text-sm text-text-secondary">
                <p className="font-semibold text-text-primary">Node states</p>
                <ul className="mt-3 space-y-2">
                  <li className="flex items-center gap-2">
                    <span className="h-3 w-3 rounded-full bg-accent-amber" />{" "}
                    suspected_root
                  </li>
                  <li className="flex items-center gap-2">
                    <span className="h-3 w-3 rounded-full bg-accent-red" />{" "}
                    primary_affected
                  </li>
                  <li className="flex items-center gap-2">
                    <span className="h-3 w-3 rounded-full bg-accent-emerald" />{" "}
                    impact_path
                  </li>
                  <li className="flex items-center gap-2">
                    <span className="h-3 w-3 rounded-full bg-accent-purple" />{" "}
                    blast_radius
                  </li>
                </ul>
              </div>
              <div className="glass-inset p-4 text-sm text-text-secondary">
                <p className="font-semibold text-text-primary">Edge labels</p>
                <ul className="mt-3 space-y-2">
                  <li>
                    <strong className="text-text-primary">depends_on</strong> —
                    static relationship between nodes
                  </li>
                  <li>
                    <strong className="text-text-primary">
                      sends_traffic_to
                    </strong>{" "}
                    — traffic direction used by active hypothesis
                  </li>
                </ul>
              </div>
            </div>
          </Card>
        </div>

        <aside className="space-y-6">
          <Card interactive glow="cyan">
            <h2 className="text-xl font-semibold text-text-primary">
              Ranked Hypotheses
            </h2>
            <div className="mt-4 space-y-4">
              {investigation.hypotheses.map((hypothesis) => {
                const evidenceItems =
                  evidenceByHypothesis[hypothesis.hypothesis_id] ?? [];
                const missingEvidence = evidenceItems.filter(
                  (item) => item.kind === "missing",
                );
                const confirmed =
                  reviewStatus[hypothesis.hypothesis_id] === "confirmed";
                const busy = Boolean(busyHypothesis[hypothesis.hypothesis_id]);
                return (
                  <article
                    key={hypothesis.hypothesis_id}
                    data-testid={hypothesisRowTestId(hypothesis.hypothesis_id)}
                    className="glass-inset animate-fade-in-up p-4"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <p className="text-xs font-bold uppercase tracking-widest text-accent-cyan">
                          Rank {hypothesis.rank}
                        </p>
                        <p className="mt-2 text-lg font-semibold text-text-primary">
                          {confirmed
                            ? "Confirmed root cause"
                            : hypothesis.candidate_entity_id}
                        </p>
                        {!confirmed ? (
                          <p className="text-sm text-text-secondary">
                            {hypothesis.hypothesis_type}
                          </p>
                        ) : null}
                      </div>
                      <EvidenceScoreBar score={hypothesis.evidence_score} />
                    </div>
                    <div className="mt-4 rounded-2xl border border-border-subtle bg-white/[0.02] p-4 text-sm text-text-secondary">
                      {hypothesis.evidence_coverage.available}/
                      {hypothesis.evidence_coverage.expected} expected evidence
                      requirements available
                    </div>
                    <details className="mt-4 rounded-2xl border border-border-subtle bg-white/[0.02] p-4">
                      <summary className="cursor-pointer text-sm font-semibold text-text-primary">
                        Factor breakdown
                      </summary>
                      <div className="mt-3 grid gap-3 sm:grid-cols-2">
                        {Object.entries(hypothesis.factor_scores).map(
                          ([factor, score]) => (
                            <div
                              key={factor}
                              className="rounded-xl border border-border-subtle bg-surface-soft p-3 text-sm"
                            >
                              <UiTooltip label={`Contribution of ${factor.replace(/_/g, " ")} to the overall evidence score`}>
                                <p className="cursor-help font-semibold text-text-primary underline decoration-dotted decoration-text-muted underline-offset-4">
                                  {factor}
                                </p>
                              </UiTooltip>
                              <p className="mt-1 text-text-secondary">
                                {Number(score).toFixed(2)}
                              </p>
                            </div>
                          ),
                        )}
                      </div>
                    </details>
                    <div className="mt-4 flex flex-wrap gap-3">
                      <Button
                        variant="success"
                        data-testid={hypothesisConfirmTestId(hypothesis.hypothesis_id)}
                        aria-label="Confirm hypothesis"
                        icon={<CheckIcon className="h-4 w-4" />}
                        loading={busy}
                        disabled={busy}
                        onClick={() =>
                          postReview(hypothesis.hypothesis_id, "confirmed")
                        }
                      >
                        Confirm
                      </Button>
                      <Button
                        variant="danger"
                        data-testid={hypothesisRejectTestId(hypothesis.hypothesis_id)}
                        aria-label="Reject hypothesis"
                        icon={<XIcon className="h-4 w-4" />}
                        loading={busy}
                        disabled={busy}
                        onClick={() =>
                          postReview(hypothesis.hypothesis_id, "rejected")
                        }
                      >
                        Reject
                      </Button>
                      <Button
                        variant="warning"
                        data-testid={evidenceRequestTestId(hypothesis.hypothesis_id)}
                        aria-label="Request evidence"
                        icon={<HelpCircleIcon className="h-4 w-4" />}
                        loading={busy}
                        disabled={busy || missingEvidence.length === 0}
                        onClick={() =>
                          postReview(
                            hypothesis.hypothesis_id,
                            "evidence_requested",
                            missingEvidence[0]?.evidence_id,
                          )
                        }
                      >
                        Request evidence
                      </Button>
                    </div>
                  </article>
                );
              })}
            </div>
          </Card>

          <Card
            interactive
            glow="purple"
            data-testid={TEST_IDS.evidencePanel}
          >
            <h2 className="text-xl font-semibold text-text-primary">
              Evidence Explorer
            </h2>
            <p className="mt-2 text-sm text-text-secondary">
              Verified observed facts, correlated signals, conflicting
              evidence, and missing evidence.
            </p>
            <div className="mt-4 space-y-3">
              {(
                [
                  "observed",
                  "correlated",
                  "conflicting",
                  "missing",
                ] as components["schemas"]["EvidenceKind"][]
              ).map((kind) => {
                const KindIcon = EVIDENCE_KIND_ICON[kind];
                return (
                  <details
                    key={kind}
                    className="glass-inset p-4"
                  >
                    <summary className="flex cursor-pointer items-center gap-2 font-semibold text-text-primary">
                      <KindIcon className="h-4 w-4 shrink-0" />
                      {EVIDENCE_KIND_LABEL[kind]}
                    </summary>
                    <div className="mt-3 space-y-3">
                      {groupedEvidence[kind].length === 0 ? (
                        <EmptyState message="No items in this category." />
                      ) : (
                        groupedEvidence[kind].map((item) => (
                          <button
                            key={item.evidence_id}
                            data-testid={TEST_IDS.evidenceItem}
                            className={`w-full rounded-2xl border p-4 text-left text-sm transition-colors ${
                              kind === "conflicting"
                                ? "border-accent-amber/30 bg-accent-amber/10 text-accent-amber"
                                : kind === "missing"
                                  ? "border-border-subtle bg-white/[0.02] text-text-primary hover:bg-white/[0.05]"
                                  : "border-border-subtle bg-white/[0.02] text-text-primary hover:bg-white/[0.05]"
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
                              <div className="min-w-0">
                                <p className="font-semibold">{item.statement}</p>
                                {kind === "observed" ? (
                                  <p className="mt-1 text-xs text-text-muted">
                                    Confirms the record and value were
                                    observed; does not confirm causation
                                  </p>
                                ) : null}
                              </div>
                              <span className="shrink-0 text-xs font-semibold uppercase tracking-wide text-text-muted">
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
                );
              })}
            </div>
          </Card>

          <Card interactive glow="emerald">
            <div className="flex items-center gap-2">
              <SparklesIcon className="h-5 w-5 text-accent-emerald" />
              <h2 className="text-xl font-semibold text-text-primary">
                Explanation summary
              </h2>
            </div>
            <p className="mt-2 text-sm text-text-secondary">
              Diagnostic summary from the current investigation snapshot.
            </p>
            <div className="glass-inset mt-4 p-4 text-sm text-text-secondary">
              <p className="font-semibold text-text-primary">
                {investigation.explanation.summary}
              </p>
              <p className="mt-2">
                Generator:{" "}
                <span className="font-semibold text-text-primary">
                  {investigation.explanation.generator}
                </span>
              </p>
              <p className="mt-2 text-text-muted">
                {investigation.explanation.claims.length} supporting claims
              </p>
            </div>
          </Card>

          <Card interactive glow="cyan">
            <div className="flex items-center gap-2">
              <ClipboardListIcon className="h-5 w-5 text-accent-cyan" />
              <h2 className="text-xl font-semibold text-text-primary">
                Catalogue Recommendations
              </h2>
            </div>
            <p className="mt-2 text-sm text-text-secondary">
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
                    className="glass-inset p-4"
                  >
                    <p className="font-semibold text-text-primary">
                      Catalogue recommendation — not executed
                    </p>
                    <p className="mt-2 text-sm text-text-secondary">
                      {recommendation.title}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2 text-xs text-text-muted">
                      <span className="rounded-full border border-border-subtle px-2 py-1">
                        step_id: {recommendation.step_id}
                      </span>
                      <span className="rounded-full border border-border-subtle px-2 py-1">
                        risk_level: {recommendation.risk_level}
                      </span>
                      <span className="rounded-full border border-border-subtle px-2 py-1">
                        requires_human_approval:{" "}
                        {recommendation.requires_human_approval ? "yes" : "no"}
                      </span>
                    </div>
                  </div>
                ));
              })}
            </div>
          </Card>

          <Card
            interactive
            glow="purple"
            data-testid={TEST_IDS.auditTrailPanel}
          >
            <h2 className="text-xl font-semibold text-text-primary">
              Audit Trail
            </h2>
            <p className="mt-2 text-sm text-text-secondary">
              Append-only table showing action history for this incident.
            </p>
            <label className="relative mt-4 block text-sm font-medium text-text-secondary">
              Filter audit entries
              <span className="pointer-events-none absolute left-3 top-[calc(50%+0.3rem)] text-text-muted">
                <SearchIcon className="h-4 w-4" />
              </span>
              <input
                value={auditFilter}
                onChange={(event) => setAuditFilter(event.target.value)}
                className="mt-2 block w-full rounded-xl border border-border-strong bg-surface py-2 pl-9 pr-3 text-sm text-text-primary shadow-sm outline-none focus:border-accent-cyan focus:ring-2 focus:ring-accent-cyan/30"
                placeholder="Type actor, action, or object"
              />
            </label>
            <div className="mt-4 overflow-x-auto rounded-2xl border border-border-subtle">
              <table className="min-w-full text-left text-sm">
                <thead className="bg-white/[0.03] text-text-secondary">
                  <tr>
                    <th className="sticky top-0 bg-white/[0.03] px-4 py-3 font-semibold">
                      Timestamp
                    </th>
                    <th className="sticky top-0 bg-white/[0.03] px-4 py-3 font-semibold">
                      Actor
                    </th>
                    <th className="sticky top-0 bg-white/[0.03] px-4 py-3 font-semibold">
                      Action
                    </th>
                    <th className="sticky top-0 bg-white/[0.03] px-4 py-3 font-semibold">
                      Object
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {filteredAuditTrail.length === 0 ? (
                    <tr>
                      <td colSpan={4} className="px-4 py-6">
                        <EmptyState message="No audit records match this filter." />
                      </td>
                    </tr>
                  ) : (
                    filteredAuditTrail.map((record) => (
                      <tr
                        key={record.audit_id}
                        className="border-t border-border-subtle transition-colors hover:bg-white/[0.03]"
                      >
                        <td className="px-4 py-3 text-text-secondary">
                          {formatDate(record.timestamp)}
                        </td>
                        <td className="px-4 py-3 text-text-secondary">
                          {record.actor_type}
                        </td>
                        <td className="px-4 py-3 text-text-secondary">
                          {record.action}
                        </td>
                        <td className="px-4 py-3 text-text-secondary">
                          {record.object_type} {record.object_id}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        </aside>
      </section>

      {selectedEvent ? (
        <div className="animate-fade-in fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4 backdrop-blur-sm">
          <div className="glass-panel animate-scale-in max-h-[90vh] w-full max-w-3xl overflow-auto p-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-xl font-semibold text-text-primary">
                  Raw CanonicalEvent
                </h2>
                <p className="mt-1 text-sm text-text-secondary">
                  Attachment score and reasons accompany the raw event.
                </p>
              </div>
              <Button
                variant="ghost"
                data-testid={TEST_IDS.evidenceCloseModal}
                aria-label="Close event details modal"
                icon={<XIcon className="h-4 w-4" />}
                onClick={closeEventModal}
                className="px-3 py-2"
              />
            </div>
            <div className="glass-inset mt-6 p-4 text-sm text-text-secondary">
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
