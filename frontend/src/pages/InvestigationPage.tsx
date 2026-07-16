import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import {
  Background,
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
  type ScatterShapeProps,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { components } from "../contracts/openapi";
import { ApiClientError } from "../api/client";
import { eventsApi } from "../api/events";
import { incidentsApi } from "../api/incidents";
import {
  TEST_IDS,
  auditRowTestId,
  evidenceItemTestId,
  evidenceSectionTestId,
  evidenceSectionToggleTestId,
  factorBreakdownTestId,
  factorTooltipTestId,
  observedEvidenceTooltipTestId,
  evidenceRequestTestId,
  hypothesisConfirmTestId,
  hypothesisRejectTestId,
  hypothesisRowTestId,
  timelineEventTestId,
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
  FileTextIcon,
  HelpCircleIcon,
  InfoIcon,
  LinkIcon,
  NetworkIcon,
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

type TimelineScatterShapeProps = Omit<ScatterShapeProps, "payload"> & {
  payload?: TimelinePoint;
};

type SelectedDetail =
  | {
      kind: "event";
      event: components["schemas"]["CanonicalEvent"];
      attachment_score?: number;
      attachment_reasons?: string[];
      attachment_decision?: "attached" | "excluded";
    }
  | {
      kind: "collection_request";
      evidence_id: string;
      statement: string;
      reason_code: string;
    };

const laneOrder: components["schemas"]["Modality"][] = [
  "metric",
  "log",
  "alert",
  "config_change",
  "trace",
];
const laneLabels: Record<components["schemas"]["Modality"], string> = {
  metric: "Metric",
  log: "Log",
  alert: "Alert",
  config_change: "Config Change",
  trace: "Trace",
};
const laneColor: Record<components["schemas"]["Modality"], string> = {
  metric: "#22d3ee",
  log: "#34d399",
  alert: "#fbbf24",
  config_change: "#a78bfa",
  trace: "#fb7185",
};

const CHART_COLORS = {
  gridStroke: "rgba(148, 163, 184, 0.14)",
  axisTick: "#94a3b8",
  excludedDot: "#475569",
};

const EDGE_RELATION_STYLE: Record<string, CSSProperties> = {
  sends_traffic_to: {
    stroke: "#38bdf8",
    strokeWidth: 1.75,
  },
  depends_on: {
    stroke: "#a78bfa",
    strokeDasharray: "6 4",
    strokeWidth: 1.75,
  },
};

const NODE_BASE_CLASS =
  "font-data w-[180px] rounded px-3 py-2.5 text-center text-xs font-semibold shadow-glass";

const NODE_STATE_STYLE: Record<string, CSSProperties> = {
  suspected_root: {
    backgroundColor: "#3b2605",
    border: "1px solid #92400e",
    borderLeft: "4px solid #f59e0b",
    color: "#fef3c7",
  },
  primary_affected: {
    backgroundColor: "#3b1117",
    border: "1px solid #991b1b",
    borderLeft: "4px solid #f87171",
    color: "#fee2e2",
  },
  impact_path: {
    backgroundColor: "#052e25",
    border: "1px solid #047857",
    borderLeft: "4px solid #4ade80",
    color: "#d1fae5",
  },
  blast_radius: {
    backgroundColor: "#2e1b4f",
    border: "1px solid #6d28d9",
    borderLeft: "4px solid #a78bfa",
    color: "#ede9fe",
  },
};
const NODE_STATE_FALLBACK_STYLE: CSSProperties = {
  backgroundColor: "#111827",
  border: "1px solid #475569",
  borderLeft: "4px solid #64748b",
  color: "#e2e8f0",
};

const TOPOLOGY_POSITIONS: Record<string, { x: number; y: number }> = {
  "api-gateway-01": { x: 330, y: 20 },
  "auth-api-01": { x: 650, y: 20 },
  "checkout-api-01": { x: 170, y: 170 },
  "payment-api-01": { x: 490, y: 170 },
  "payment-db-01": { x: 490, y: 320 },
  "hdfs-client-01": { x: 90, y: 20 },
  "namenode-01": { x: 330, y: 170 },
  "datanode-01": { x: 570, y: 320 },
};

const FACTOR_WEIGHTS: Record<string, number> = {
  symptom_compatibility: 25,
  topology_relevance: 20,
  direct_logs_alerts: 15,
  propagation_consistency: 15,
  metric_anomaly: 10,
  change_causal_fit: 10,
  temporal_proximity: 3,
  historical_similarity: 2,
};

function createUuid() {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

function severityBadgeVariant(severity: number): BadgeVariant {
  if (severity >= 0.9) return "danger";
  if (severity >= 0.5) return "warning";
  return "success";
}

function severityLabel(severity: number) {
  if (severity >= 0.9) return "critical";
  if (severity >= 0.75) return "high";
  if (severity >= 0.5) return "medium";
  return "low";
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

function relativeTime(timestamp: string, reference: string) {
  const delta = Math.max(0, Date.parse(reference) - Date.parse(timestamp));
  const seconds = Math.round(delta / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return formatDate(timestamp);
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

export function InvestigationPage({ incidentId }: InvestigationPageProps) {
  const [investigation, setInvestigation] =
    useState<InvestigationResponse | null>(null);
  const [auditTrail, setAuditTrail] = useState<
    components["schemas"]["AuditRecord"][]
  >([]);
  const [selectedDetail, setSelectedDetail] = useState<SelectedDetail | null>(null);
  const [reviewStatus, setReviewStatus] = useState<Record<string, string>>({});
  const [busyHypothesis, setBusyHypothesis] = useState<Record<string, boolean>>(
    {},
  );
  const [banner, setBanner] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [auditFilter, setAuditFilter] = useState<"all" | "system" | "user" | "review">("all");
  const latestRevisionRef = useRef<number | null>(null);
  const latestGeneratedAtRef = useRef(0);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [exportingHandover, setExportingHandover] = useState<"md" | "pdf" | null>(null);
  const modalRef = useRef<HTMLDivElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  const loadInvestigation = useCallback(async (signal?: AbortSignal) => {
    try {
      setIsRefreshing(true);
      const response = await incidentsApi.getInvestigation(incidentId, signal);
      if (signal?.aborted) return;
      const revision = response.analysis_run.revision;
      const generatedAt = Date.parse(response.generated_at);
      if (
        latestRevisionRef.current !== null &&
        (revision < latestRevisionRef.current ||
          (revision === latestRevisionRef.current &&
            !Number.isNaN(generatedAt) &&
            generatedAt < latestGeneratedAtRef.current))
      ) {
        return;
      }
      if (latestRevisionRef.current !== null && revision > latestRevisionRef.current) {
        setBanner("Analysis updated; now displaying the latest snapshot.");
      }
      latestRevisionRef.current = revision;
      if (!Number.isNaN(generatedAt)) latestGeneratedAtRef.current = generatedAt;
      setInvestigation(response);
      setApiError(null);
    } catch (error) {
      if (!signal?.aborted) {
        setApiError(
          error instanceof ApiClientError
            ? `${error.payload.code}: ${error.payload.message}`
            : "UNEXPECTED_ERROR: Unable to load investigation snapshot",
        );
      }
    } finally {
      if (!signal?.aborted) setIsRefreshing(false);
    }
  }, [incidentId]);

  usePolling(loadInvestigation);

  const loadAudit = useCallback(async (signal?: AbortSignal) => {
    try {
      const response = await incidentsApi.getAudit(incidentId, signal);
      if (!signal?.aborted) setAuditTrail(response.items);
    } catch {
      // Keep the last append-only view if an audit refresh fails.
    }
  }, [incidentId]);

  useEffect(() => {
    if (investigation) void loadAudit();
  }, [investigation?.analysis_run_id, loadAudit]);

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

  function openTimelineModal(point: TimelinePoint, trigger?: HTMLElement) {
    returnFocusRef.current = trigger ?? (document.activeElement as HTMLElement);
    setSelectedDetail({
      kind: "event",
      event: point.event,
      attachment_score: point.attachment_score,
      attachment_reasons: point.attachment_reasons,
      attachment_decision: point.attached ? "attached" : "excluded",
    });
  }

  function closeDetailModal() {
    setSelectedDetail(null);
    window.setTimeout(() => returnFocusRef.current?.focus(), 0);
  }

  async function openEvidenceItem(
    item: components["schemas"]["EvidenceItem"],
    trigger: HTMLElement,
  ) {
    returnFocusRef.current = trigger;
    if (item.kind === "missing" || !item.source_event_id) {
      setSelectedDetail({
        kind: "collection_request",
        evidence_id: item.evidence_id,
        statement: item.statement,
        reason_code: item.reason_code,
      });
      return;
    }

    const timelineItem = investigation?.timeline.find(
      (entry) => entry.event.event_id === item.source_event_id,
    );
    if (timelineItem) {
      openTimelineModal(
        {
          x: Date.parse(timelineItem.event.timestamp),
          y: laneOrder.indexOf(timelineItem.event.modality),
          event: timelineItem.event,
          attachment_score: timelineItem.attachment_score,
          attachment_reasons: timelineItem.attachment_reasons,
          modality: timelineItem.event.modality,
          attached: timelineItem.attachment_decision === "attached",
        },
        trigger,
      );
      return;
    }

    try {
      setSelectedDetail({ kind: "event", event: await eventsApi.get(item.source_event_id) });
    } catch (error) {
      setApiError(
        error instanceof ApiClientError
          ? `${error.payload.code}: ${error.payload.message}`
          : "UNEXPECTED_ERROR: Unable to load evidence event",
      );
    }
  }

  useEffect(() => {
    if (!selectedDetail) return;
    closeButtonRef.current?.focus();
    const modal = modalRef.current;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeDetailModal();
      if (event.key !== "Tab" || !modal) return;
      const focusable = Array.from(
        modal.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [selectedDetail]);

  async function postReview(
    hypothesisId: string,
    decision: "confirmed" | "rejected" | "evidence_requested",
    requestedEvidenceId?: string,
  ) {
    setBanner(null);
    setBusyHypothesis((current) => ({ ...current, [hypothesisId]: true }));

    if (!investigation) return;
    const body: components["schemas"]["ReviewRequest"] = {
      analysis_run_id: investigation.analysis_run_id,
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
      await incidentsApi.submitReview(incidentId, body);
      setReviewStatus((current) => ({ ...current, [hypothesisId]: decision }));
      if (decision === "confirmed") {
        setBanner("Confirmed root cause");
      }
      await Promise.all([loadInvestigation(), loadAudit()]);
    } catch (error) {
      if (error instanceof ApiClientError && error.status === 409) {
        const code = error.payload.code;
        if (code === "STALE_ANALYSIS") {
          setBanner("Analysis updated, refresh the page");
        } else if (code === "REVIEW_CONFLICT") {
          setBanner("Decision already recorded");
        } else if (code === "INCIDENT_CLOSED") {
          setBanner("Incident is closed; review controls are read-only");
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

  async function downloadHandover(format: "md" | "pdf") {
    setExportingHandover(format);
    setApiError(null);
    try {
      const file = await incidentsApi.downloadHandover(incidentId, format);
      const url = window.URL.createObjectURL(file.blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = file.filename;
      document.body.appendChild(link);
      try {
        link.click();
      } finally {
        link.remove();
        window.URL.revokeObjectURL(url);
      }
      setBanner(`${format === "pdf" ? "PDF" : "Markdown"} shift-handover report downloaded.`);
    } catch (error) {
      setApiError(
        error instanceof ApiClientError
          ? `${error.payload.code}: ${error.payload.message}`
          : "UNEXPECTED_ERROR: Unable to generate shift-handover report",
      );
    } finally {
      setExportingHandover(null);
    }
  }

  if (!investigation) {
    if (apiError) {
      return <EmptyState message={apiError} />;
    }
    return <PageSkeleton label="Loading incident investigation..." />;
  }

  const filteredAuditTrail = auditTrail.filter((record) => {
    if (auditFilter === "all") return true;
    if (auditFilter === "review") return record.action.includes("REVIEW");
    return record.actor_type === auditFilter;
  });
  const explanationFallbackUsed = auditTrail.some(
    (record) => record.action === "EXPLANATION_FALLBACK_USED",
  );
  const topHypothesis = [...investigation.hypotheses].sort(
    (left, right) => left.rank - right.rank,
  )[0];
  const topEvidence = topHypothesis
    ? evidenceByHypothesis[topHypothesis.hypothesis_id] ?? []
    : [];
  const topMissingEvidence = topEvidence.filter((item) => item.kind === "missing");
  const topBusy = topHypothesis
    ? Boolean(busyHypothesis[topHypothesis.hypothesis_id])
    : false;
  const incidentClosed = ["resolved", "rejected"].includes(investigation.incident.status);
  const topTerminal = topHypothesis
    ? investigation.reviews.some(
        (review) =>
          review.hypothesis_id === topHypothesis.hypothesis_id &&
          ["confirmed", "rejected"].includes(review.decision),
      )
    : false;

  return (
    <main
      data-testid={TEST_IDS.investigationPanel}
      className="mx-auto max-w-7xl space-y-8 p-4 sm:p-6 lg:p-8"
    >
      <Card as="header" glow="none" className="space-y-3 border-l-2 border-l-accent-red p-5">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <p className="font-data flex items-center gap-1.5 text-xs text-text-secondary">
              <ClockIcon className="h-3.5 w-3.5" />
              Analysis run {investigation.analysis_run_id}
            </p>
            <h1 className="mt-1 break-words text-2xl font-semibold tracking-tight text-text-primary">
              {investigation.incident.title}
            </h1>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Badge variant={severityBadgeVariant(investigation.incident.severity)}>
                ⚠ {severityLabel(investigation.incident.severity)} severity
              </Badge>
              <Badge data-testid={TEST_IDS.incidentStatus} variant={statusBadgeVariant(investigation.incident.status)}>
                ● {investigation.incident.status}
              </Badge>
              <span className="text-sm text-text-secondary">
                Current incident status
              </span>
            </div>
          </div>
          <div className="flex shrink-0 flex-col gap-3 md:max-w-sm">
            <div className="glass-inset px-4 py-3 text-sm text-text-secondary">
              Affected entities:{" "}
              <span className="font-data font-semibold text-text-primary">
                {Array.from(
                  new Set(investigation.incident.affected_entity_ids),
                ).join(", ")}
              </span>
            </div>
            <div className="flex flex-wrap justify-end gap-2" aria-label="Export shift-handover report">
              <Button
                variant="secondary"
                icon={<FileTextIcon aria-hidden="true" />}
                loading={exportingHandover === "md"}
                disabled={exportingHandover !== null}
                data-testid={TEST_IDS.handoverMarkdown}
                onClick={() => void downloadHandover("md")}
              >
                Markdown
              </Button>
              <Button
                variant="primary"
                icon={<FileTextIcon aria-hidden="true" />}
                loading={exportingHandover === "pdf"}
                disabled={exportingHandover !== null}
                data-testid={TEST_IDS.handoverPdf}
                onClick={() => void downloadHandover("pdf")}
              >
                PDF handover
              </Button>
            </div>
          </div>
        </div>
        {banner ? (
          <div
            role="status"
            aria-live="polite"
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
            aria-live="assertive"
            data-testid={TEST_IDS.genericBanner}
            className="glass-panel flex items-center gap-2 border-accent-red/30 bg-accent-red/10 px-4 py-3 text-sm font-semibold text-accent-red"
          >
            <AlertTriangleIcon className="h-4 w-4 shrink-0" aria-hidden="true" />{" "}
            {apiError}
          </div>
        ) : null}
      </Card>

      {topHypothesis ? (
        <Card
          as="section"
          data-testid="top-hypothesis"
          className="border-l-2 border-l-accent-cyan p-5"
        >
          <div className="grid gap-5 lg:grid-cols-[1fr_280px] lg:items-start">
            <div>
              <p className="text-sm font-medium text-text-secondary">Top-ranked hypothesis</p>
              <h2 className="font-data mt-1 text-xl font-semibold text-text-primary">
                {topHypothesis.hypothesis_type}
              </h2>
              <p className="font-data mt-1 text-sm text-accent-cyan">
                {topHypothesis.candidate_entity_id}
              </p>
              <p className="mt-3 max-w-3xl text-sm text-text-secondary">
                {investigation.explanation.summary}
              </p>
            </div>
            <EvidenceScoreBar
              score={topHypothesis.evidence_score}
              available={topHypothesis.evidence_coverage.available}
              expected={topHypothesis.evidence_coverage.expected}
            />
          </div>
          <div className="mt-5 flex flex-wrap gap-2 border-t border-border-subtle pt-4">
            <Button
              variant="success"
              data-testid="top-hypothesis-confirm"
              loading={topBusy}
              disabled={topBusy || incidentClosed || topTerminal}
              onClick={() => postReview(topHypothesis.hypothesis_id, "confirmed")}
            >
              Confirm
            </Button>
            <Button
              variant="danger"
              data-testid="top-hypothesis-reject"
              loading={topBusy}
              disabled={topBusy || incidentClosed || topTerminal}
              onClick={() => postReview(topHypothesis.hypothesis_id, "rejected")}
            >
              Reject
            </Button>
            <Button
              variant="warning"
              data-testid="top-hypothesis-request-evidence"
              loading={topBusy}
              disabled={topBusy || incidentClosed || topMissingEvidence.length === 0}
              onClick={() =>
                postReview(
                  topHypothesis.hypothesis_id,
                  "evidence_requested",
                  topMissingEvidence[0]?.evidence_id,
                )
              }
            >
              Request evidence
            </Button>
          </div>
        </Card>
      ) : null}

      <section className="grid gap-6 xl:grid-cols-[3fr_2fr]">
        <div className="contents">
          <Card interactive glow="cyan" className="order-3 xl:col-span-2">
            <div className="flex items-center gap-2">
              <ClockIcon className="h-5 w-5 text-accent-cyan" />
              <h2 className="text-xl font-semibold text-text-primary">
                Incident Timeline
              </h2>
            </div>
            <p className="mt-2 text-sm text-text-secondary">
              One aligned time axis with five lanes. Click an event to inspect
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
                    tickFormatter={(value) => laneLabels[laneOrder[Number(value)]] ?? ""}
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
                    shape={(props: TimelineScatterShapeProps) => {
                      const { cx, cy, payload } = props;
                      if (cx == null || cy == null || !payload) {
                        return null;
                      }
                      const point = payload;
                      return (
                        <circle
                          cx={cx}
                          cy={cy}
                          r={point.attached ? 8 : 6}
                          data-attached={String(point.attached)}
                          data-testid={timelineEventTestId(point.event.event_id)}
                          role="button"
                          tabIndex={0}
                          aria-label={`${point.attached ? "Attached" : "Excluded"} ${laneLabels[point.modality]} event ${point.event.event_type}`}
                          fill={eventColor(point)}
                          stroke={point.attached ? "#e2e8f0" : "#64748b"}
                          strokeWidth={point.attached ? 2 : 1}
                          className="cursor-pointer"
                          onClick={(event) => openTimelineModal(point, event.currentTarget as unknown as HTMLElement)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              openTimelineModal(point, event.currentTarget as unknown as HTMLElement);
                            }
                          }}
                        />
                      );
                    }}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <Card interactive glow="purple" className="order-4 xl:col-span-2">
            <div className="flex items-center gap-2">
              <NetworkIcon className="h-5 w-5 text-accent-purple" />
              <h2 className="text-xl font-semibold text-text-primary">
                Topology Impact Graph
              </h2>
            </div>
            <p className="mt-2 text-sm text-text-secondary">
              Topology is rendered from the single investigation snapshot;
              edge color and line style encode relation_type, while node color
              encodes investigation state.
            </p>
            <div
              className="glass-inset mt-6 h-[420px] overflow-hidden"
              data-testid={TEST_IDS.topologyGraph}
            >
              <ReactFlow
                className="react-flow-dark"
                nodes={investigation.topology.nodes.map((node, index) => ({
                  id: node.id,
                  position: TOPOLOGY_POSITIONS[node.id] ?? {
                    x: (index % 3) * 260 + 50,
                    y: Math.floor(index / 3) * 150 + 40,
                  },
                  data: { label: `${node.name}` },
                  className: NODE_BASE_CLASS,
                  style:
                    NODE_STATE_STYLE[String(node.state)] ??
                    NODE_STATE_FALLBACK_STYLE,
                }))}
                edges={investigation.topology.edges.map((edge, index) => ({
                  id: `${edge.source}-${edge.target}-${edge.relation_type}-${index}`,
                  source: edge.source,
                  target: edge.target,
                  type: "smoothstep",
                  ariaLabel: `${edge.source} ${edge.relation_type} ${edge.target}`,
                  pathOptions: {
                    offset: edge.relation_type === "depends_on" ? 24 : 12,
                  },
                  style:
                    EDGE_RELATION_STYLE[edge.relation_type] ?? {
                      stroke: "#64748b",
                      strokeWidth: 1.5,
                    },
                  animated: false,
                }))}
                fitView
                fitViewOptions={{ padding: 0.16 }}
              >
                <Background gap={16} />
              </ReactFlow>
            </div>
            <div className="font-data mt-4 flex flex-wrap items-center gap-3 text-xs text-text-secondary">
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-accent-amber" />suspected_root</span>
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-accent-red" />primary_affected</span>
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-accent-emerald" />impact_path</span>
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-accent-purple" />blast_radius</span>
              <span className="flex items-center gap-1.5"><span className="w-5 border-t-2 border-accent-cyan" />sends_traffic_to</span>
              <span className="flex items-center gap-1.5"><span className="w-5 border-t-2 border-dashed border-accent-purple" />depends_on</span>
              <details className="ml-auto">
                <summary className="cursor-pointer text-accent-cyan">Edge semantics</summary>
                <p className="mt-2 max-w-xl text-text-secondary">depends_on follows service dependencies; sends_traffic_to follows traffic impact. Reverse traversal identifies affected upstream services.</p>
              </details>
            </div>
          </Card>
        </div>

        <aside className="contents">
          <Card interactive glow="cyan" className="order-2">
            <h2 className="text-lg font-semibold text-text-primary">
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
                  reviewStatus[hypothesis.hypothesis_id] === "confirmed" ||
                  investigation.incident.confirmed_hypothesis_id === hypothesis.hypothesis_id ||
                  investigation.reviews.some(
                    (review) => review.hypothesis_id === hypothesis.hypothesis_id && review.decision === "confirmed",
                  );
                const busy = Boolean(busyHypothesis[hypothesis.hypothesis_id]);
                const closed = ["resolved", "rejected"].includes(investigation.incident.status);
                const terminal = investigation.reviews.some(
                  (review) => review.hypothesis_id === hypothesis.hypothesis_id && ["confirmed", "rejected"].includes(review.decision),
                );
                return (
                  <article
                    key={hypothesis.hypothesis_id}
                    data-testid={hypothesisRowTestId(hypothesis.hypothesis_id)}
                    className="glass-inset border-l-2 border-l-border-strong p-4"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <p className="text-xs font-medium text-text-muted">
                          Rank {hypothesis.rank}
                        </p>
                        <p className="font-data mt-2 text-sm font-semibold text-text-primary">
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
                      <EvidenceScoreBar
                        score={hypothesis.evidence_score}
                        available={hypothesis.evidence_coverage.available}
                        expected={hypothesis.evidence_coverage.expected}
                      />
                    </div>
                    <div className="font-data mt-4 rounded border border-border-subtle bg-surface-soft p-3 text-xs text-text-secondary">
                      {hypothesis.evidence_coverage.available}/
                      {hypothesis.evidence_coverage.expected} expected evidence
                      requirements available
                    </div>
                    <details className="mt-4 rounded border border-border-subtle bg-surface-soft p-3">
                      <summary
                        data-testid={factorBreakdownTestId(hypothesis.hypothesis_id)}
                        aria-label={`Toggle factor breakdown for ${hypothesis.hypothesis_type}`}
                        className="cursor-pointer text-sm font-semibold text-text-primary"
                      >
                        Factor breakdown
                      </summary>
                      <div className="mt-3 space-y-2">
                        {Object.entries(hypothesis.factor_scores).map(
                          ([factor, score]) => (
                            <div
                              key={factor}
                              className="grid grid-cols-[minmax(110px,1fr)_minmax(90px,1.4fr)_42px] items-center gap-2 text-xs"
                            >
                              <UiTooltip
                                label={`Contribution of ${factor.replace(/_/g, " ")} to the overall evidence score`}
                                testId={factorTooltipTestId(hypothesis.hypothesis_id, factor)}
                              >
                                <p className="font-data cursor-help truncate text-text-secondary" title={factor}>
                                  {factor} <span className="text-text-muted">({FACTOR_WEIGHTS[factor] ?? 0}%)</span>
                                </p>
                              </UiTooltip>
                              <span className="h-1.5 overflow-hidden rounded-sm bg-white/10"><span className="block h-full bg-accent-cyan" style={{ width: `${Math.max(0, Math.min(1, Number(score))) * 100}%` }} /></span>
                              <span className="font-data text-right text-text-primary">{Number(score).toFixed(2)}</span>
                            </div>
                          ),
                        )}
                      </div>
                    </details>
                    <div className="mt-4 flex flex-wrap gap-3">
                      <Button
                        variant="success"
                        data-testid={hypothesisConfirmTestId(hypothesis.hypothesis_id)}
                        aria-label={`Confirm ${hypothesis.hypothesis_type} hypothesis`}
                        icon={<CheckIcon className="h-4 w-4" />}
                        loading={busy}
                        disabled={busy || closed || terminal}
                        onClick={() =>
                          postReview(hypothesis.hypothesis_id, "confirmed")
                        }
                      >
                        Confirm
                      </Button>
                      <Button
                        variant="danger"
                        data-testid={hypothesisRejectTestId(hypothesis.hypothesis_id)}
                        aria-label={`Reject ${hypothesis.hypothesis_type} hypothesis`}
                        icon={<XIcon className="h-4 w-4" />}
                        loading={busy}
                        disabled={busy || closed || terminal}
                        onClick={() =>
                          postReview(hypothesis.hypothesis_id, "rejected")
                        }
                      >
                        Reject
                      </Button>
                      <Button
                        variant="warning"
                        data-testid={evidenceRequestTestId(hypothesis.hypothesis_id)}
                        aria-label={`Request missing evidence for ${hypothesis.hypothesis_type}`}
                        icon={<HelpCircleIcon className="h-4 w-4" />}
                        loading={busy}
                        disabled={busy || closed || missingEvidence.length === 0}
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
            className="order-1"
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
                    data-testid={evidenceSectionTestId(kind)}
                    className="glass-inset p-4"
                  >
                    <summary
                      data-testid={evidenceSectionToggleTestId(kind)}
                      aria-label={`Toggle ${EVIDENCE_KIND_LABEL[kind]}`}
                      className="flex cursor-pointer items-center gap-2 font-semibold text-text-primary"
                    >
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
                            data-testid={evidenceItemTestId(item.evidence_id)}
                            aria-label={kind === "missing" ? `Open collection request: ${item.statement}` : `Open source record: ${item.statement}`}
                            className={`w-full rounded border-l-2 p-3 text-left text-sm transition-colors ${
                              kind === "conflicting"
                                ? "border-accent-amber/30 bg-accent-amber/10 text-accent-amber"
                                : kind === "missing"
                                  ? "border-border-subtle bg-white/[0.02] text-text-primary hover:bg-white/[0.05]"
                                  : "border-border-subtle bg-white/[0.02] text-text-primary hover:bg-white/[0.05]"
                            }`}
                            onClick={(event) => void openEvidenceItem(item, event.currentTarget)}
                          >
                            <div className="flex items-center justify-between gap-3">
                              <div className="min-w-0">
                                <p className="font-semibold">
                                  {kind === "missing" ? `Collection request: ${item.statement}` : item.statement}
                                </p>
                                {kind === "observed" ? (
                                  <UiTooltip
                                    label="Confirms the record and value were observed; does not confirm causation"
                                    testId={observedEvidenceTooltipTestId(item.evidence_id)}
                                  >
                                    <span className="mt-1 inline-flex cursor-help text-xs text-text-muted underline decoration-dotted underline-offset-4">
                                      Verified observed fact — causation is not confirmed
                                    </span>
                                  </UiTooltip>
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

          <Card interactive glow="emerald" className="order-5 xl:col-span-2">
            <div className="flex items-center gap-2">
              <SparklesIcon className="h-5 w-5 text-accent-emerald" />
              <h2 className="text-xl font-semibold text-text-primary">
                Explanation summary
              </h2>
            </div>
            <p className="mt-2 text-sm text-text-secondary">
              Diagnostic summary from the current investigation snapshot.
            </p>
            {explanationFallbackUsed ? (
              <div
                role="status"
                data-testid={TEST_IDS.explanationFallbackBanner}
                className="mt-4 rounded-xl border border-accent-amber/30 bg-accent-amber/10 p-3 text-sm text-accent-amber"
              >
                Explanation validation fallback: the deterministic template was used after the optional LLM result was rejected.
              </div>
            ) : null}
            <div className="glass-inset mt-4 p-4 text-sm text-text-secondary">
              <p className="font-semibold text-text-primary">
                {investigation.explanation.summary}
              </p>
              <p className="mt-2">
                Generator:{" "}
                <span className="font-data font-semibold text-text-primary">
                  {investigation.explanation.generator}
                </span>
              </p>
              <p className="mt-2 text-text-muted">
                {investigation.explanation.claims.length} supporting claims
              </p>
            </div>
          </Card>

          <Card interactive glow="cyan" className="order-6 xl:col-span-2">
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
                    <div className="font-data mt-3 flex flex-wrap gap-2 text-xs text-text-muted">
                      <span className="rounded border border-border-subtle px-2 py-1">
                        step_id: {recommendation.step_id}
                      </span>
                      <span className="rounded border border-border-subtle px-2 py-1">
                        risk_level: {recommendation.risk_level}
                      </span>
                      <span className="rounded border border-border-subtle px-2 py-1">
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
            className="order-7 xl:col-span-2"
            data-testid={TEST_IDS.auditTrailPanel}
          >
            <h2 className="text-xl font-semibold text-text-primary">
              Audit Trail
            </h2>
            <p className="mt-2 text-sm text-text-secondary">
              Append-only table showing action history for this incident.
            </p>
            <div data-testid={TEST_IDS.auditFilter} aria-label="Filter audit entries" className="mt-4 flex flex-wrap gap-2">
              {(["all", "system", "user", "review"] as const).map((filter) => (
                <button
                  key={filter}
                  type="button"
                  aria-pressed={auditFilter === filter}
                  onClick={() => setAuditFilter(filter)}
                  className={`rounded border px-2.5 py-1 text-xs font-semibold uppercase tracking-wide ${
                    auditFilter === filter
                      ? "border-accent-cyan bg-accent-cyan/10 text-accent-cyan"
                      : "border-border-subtle text-text-secondary hover:border-border-strong"
                  }`}
                >
                  {filter}
                </button>
              ))}
            </div>
            <div className="mt-4 overflow-x-auto rounded border border-border-subtle">
              <table className="min-w-full text-left text-xs">
                <thead className="bg-surface-strong text-text-secondary">
                  <tr>
                    <th className="sticky top-0 bg-surface-strong px-3 py-2 font-semibold">
                      Timestamp
                    </th>
                    <th className="sticky top-0 bg-surface-strong px-3 py-2 font-semibold">
                      Actor
                    </th>
                    <th className="sticky top-0 bg-surface-strong px-3 py-2 font-semibold">
                      Action
                    </th>
                    <th className="sticky top-0 bg-surface-strong px-3 py-2 font-semibold">
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
                        data-testid={auditRowTestId(record.audit_id)}
                        className={`border-t border-l-2 border-border-subtle transition-colors hover:bg-surface-strong ${
                          record.action.includes("REVIEW")
                            ? "border-l-accent-emerald"
                            : record.actor_type === "user"
                              ? "border-l-accent-cyan"
                              : "border-l-text-muted"
                        }`}
                      >
                        <td className="font-data whitespace-nowrap px-3 py-2 text-text-secondary" title={formatDate(record.timestamp)}>
                          {relativeTime(record.timestamp, investigation.generated_at)}
                        </td>
                        <td className="font-data px-3 py-2 text-text-secondary">
                          {record.actor_type}
                        </td>
                        <td className="font-data px-3 py-2 font-semibold text-text-primary">
                          {record.action}
                        </td>
                        <td className="font-data max-w-xs truncate px-3 py-2 text-text-secondary" title={`${record.object_type} ${record.object_id}`}>
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

      {selectedDetail ? (
        <div className="animate-fade-in fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4">
          <div
            ref={modalRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="event-detail-title"
            data-testid={TEST_IDS.eventModal}
            className="glass-panel animate-scale-in max-h-[90vh] w-full max-w-3xl overflow-auto p-6"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 id="event-detail-title" className="text-xl font-semibold text-text-primary">
                  {selectedDetail.kind === "event" ? "Raw CanonicalEvent" : "Evidence collection request"}
                </h2>
                <p className="mt-1 text-sm text-text-secondary">
                  {selectedDetail.kind === "event"
                    ? "Attachment decision, score, and reasons accompany the raw event when available."
                    : "This missing evidence is a concrete request from the hypothesis catalogue."}
                </p>
              </div>
              <Button
                ref={closeButtonRef}
                variant="ghost"
                data-testid={TEST_IDS.evidenceCloseModal}
                aria-label="Close event details modal"
                icon={<XIcon className="h-4 w-4" />}
                onClick={closeDetailModal}
                className="px-3 py-2"
              />
            </div>
            <div data-testid={TEST_IDS.eventModalBody} className="glass-inset font-data mt-6 p-4 text-sm text-text-secondary">
              {selectedDetail.kind === "event" ? (
                <>
                  {selectedDetail.attachment_decision ? <p><strong className="text-text-primary">Attachment:</strong> {selectedDetail.attachment_decision}</p> : null}
                  {selectedDetail.attachment_score !== undefined ? <p className="mt-2"><strong className="text-text-primary">Attachment score:</strong> {selectedDetail.attachment_score}</p> : null}
                  {selectedDetail.attachment_reasons ? <p className="mt-2"><strong className="text-text-primary">Reasons:</strong> {selectedDetail.attachment_reasons.join(", ")}</p> : null}
                  <pre className="mt-4 whitespace-pre-wrap break-words text-xs">{JSON.stringify(selectedDetail.event, null, 2)}</pre>
                </>
              ) : (
                <dl className="space-y-3"><div><dt className="font-semibold text-text-primary">Request</dt><dd>{selectedDetail.statement}</dd></div><div><dt className="font-semibold text-text-primary">Reason code</dt><dd>{selectedDetail.reason_code}</dd></div><div><dt className="font-semibold text-text-primary">Evidence ID</dt><dd>{selectedDetail.evidence_id}</dd></div></dl>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
