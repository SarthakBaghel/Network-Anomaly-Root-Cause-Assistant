export const TEST_IDS = {
  simulatorStart: "simulator-start-btn",
  simulatorStop: "simulator-stop-btn",
  simulatorReset: "simulator-reset-btn",
  scenarioTrigger: "scenario-trigger-btn",
  incidentList: "incident-list",
  investigationPanel: "investigation-panel",
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
  evidenceCloseModal: "evidence-close-modal-btn",
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
