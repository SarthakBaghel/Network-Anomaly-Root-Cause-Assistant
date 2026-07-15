export const TEST_IDS = {
  simulatorStart: "simulator-start-btn",
  simulatorStop: "simulator-stop-btn",
  simulatorReset: "simulator-reset-btn",
  simulatorResetConfirm: "simulator-reset-confirm-btn",
  scenarioTrigger: "scenario-trigger-btn",
  scenarioSelect: "scenario-select",
  simulatorState: "simulator-state",
  incidentList: "incident-list",
  anomalyTable: "anomaly-table",
  anomalyFilters: "anomaly-filters",
  overviewLoading: "overview-loading",
  quarantineBanner: "quarantine-banner",
  investigationPanel: "investigation-panel",
  incidentStatus: "incident-status",
  evidencePanel: "evidence-panel",
  topologyGraph: "topology-graph",
  timelinePanel: "timeline-panel",
  auditTrailPanel: "audit-trail-panel",
  staleAnalysisBanner: "stale-analysis-banner",
  genericBanner: "generic-banner",
  hypothesisConfirm: "hypothesis-confirm-btn",
  hypothesisReject: "hypothesis-reject-btn",
  evidenceRequest: "evidence-request-btn",
  evidenceItem: "evidence-item",
  eventModal: "event-modal",
  eventModalBody: "event-modal-body",
  auditFilter: "audit-filter",
  explanationFallbackBanner: "explanation-fallback-banner",
  evidenceCloseModal: "evidence-close-modal-btn",
  sidebarOverviewLink: "sidebar-overview-link",
  sidebarIncidentLink: "sidebar-incident-link",
  sidebarToggle: "sidebar-toggle-btn",
  mobileOverviewLink: "mobile-overview-link",
  mobileIncidentLink: "mobile-incident-link",
} as const;

export const incidentRowTestId = (incidentId: string) =>
  `incident-row-${incidentId}`;
export const hypothesisRowTestId = (hypothesisId: string) =>
  `hypothesis-row-${hypothesisId}`;
export const hypothesisConfirmTestId = (hypothesisId: string) =>
  `${TEST_IDS.hypothesisConfirm}-${hypothesisId}`;
export const hypothesisRejectTestId = (hypothesisId: string) =>
  `${TEST_IDS.hypothesisReject}-${hypothesisId}`;
export const evidenceRequestTestId = (hypothesisId: string) =>
  `${TEST_IDS.evidenceRequest}-${hypothesisId}`;
export const sourceHealthTestId = (source: string) => `source-health-${source}`;
export const anomalyRowTestId = (anomalyId: string) => `anomaly-row-${anomalyId}`;
export const timelineEventTestId = (eventId: string) => `timeline-event-${eventId}`;
export const evidenceItemTestId = (evidenceId: string) => `evidence-item-${evidenceId}`;
export const evidenceSectionTestId = (kind: string) => `evidence-section-${kind}`;
export const evidenceSectionToggleTestId = (kind: string) => `evidence-section-toggle-${kind}`;
export const auditRowTestId = (auditId: string) => `audit-row-${auditId}`;
export const factorBreakdownTestId = (hypothesisId: string) =>
  `factor-breakdown-${hypothesisId}`;
export const factorTooltipTestId = (hypothesisId: string, factor: string) =>
  `factor-tooltip-${hypothesisId}-${factor}`;
export const observedEvidenceTooltipTestId = (evidenceId: string) =>
  `observed-evidence-tooltip-${evidenceId}`;
