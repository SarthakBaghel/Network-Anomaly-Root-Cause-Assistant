export const TEST_IDS = {
  simulatorStart: 'simulator-start-btn',
  simulatorStop: 'simulator-stop-btn',
  simulatorReset: 'simulator-reset-btn',
  scenarioTrigger: 'scenario-trigger-btn',
  incidentList: 'incident-list',
  investigationPanel: 'investigation-panel',
  evidencePanel: 'evidence-panel',
  topologyGraph: 'topology-graph',
  timelinePanel: 'timeline-panel',
  auditTrailPanel: 'audit-trail-panel',
  hypothesisConfirm: 'hypothesis-confirm-btn',
  hypothesisReject: 'hypothesis-reject-btn',
  evidenceRequest: 'evidence-request-btn',
  apiError: 'api-error',
  apiLoading: 'api-loading',
} as const

export const incidentRowTestId = (incidentId: string) => `incident-row-${incidentId}`
export const hypothesisRowTestId = (hypothesisId: string) => `hypothesis-row-${hypothesisId}`
export const sourceHealthTestId = (source: string) => `source-health-${source}`
