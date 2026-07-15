import { http, HttpResponse } from 'msw'

import { goldenEvents, goldenInvestigationResponse } from './fixture-validation'

const incident = goldenInvestigationResponse.incident

const SOURCE_HEALTH = [
  ['simulator.prometheus', 'metrics'],
  ['simulator.syslog', 'logs'],
  ['simulator.alertmanager', 'alerts'],
  ['simulator.config_audit', 'config_changes'],
  ['simulator.trace', 'traces'],
  ['fixture.cmdb_topology', 'topology'],
] as const

let simulatorState = 'stopped'
let scenarioState = 'idle'
let scenarioId: string | null = null
let lastResetAt: string | null = null
let mockReviews: Array<Record<string, unknown>> = []
let mockAudit: Array<Record<string, unknown>> = []

export function resetFixtureState() {
  simulatorState = 'stopped'
  scenarioState = 'idle'
  scenarioId = null
  lastResetAt = null
  mockReviews = []
  mockAudit = []
}

function simulatorStatus() {
  return {
    generated_at: new Date().toISOString(),
    state: simulatorState,
    scenario_state: scenarioState,
    scenario_id: scenarioId,
    virtual_clock: scenarioState === 'completed' ? '2026-07-14T09:32:00Z' : '2026-07-14T09:25:00Z',
    seed: 20260714,
    metric_interval_seconds: 10,
    baseline_ticks_emitted: ['baseline_complete', 'completed'].includes(scenarioState) ? 30 : scenarioState === 'baseline' ? 18 : 0,
    baseline_ticks_required: 30,
    sources: {},
    source_health: SOURCE_HEALTH.map(([source_id, source_type]) => ({
      source_id,
      source_type,
      status: source_id === 'fixture.cmdb_topology' ? 'healthy' : scenarioState === 'idle' ? 'offline' : 'healthy',
      last_ingest_at: source_id === 'fixture.cmdb_topology' ? '2026-07-14T09:00:00Z' : null,
      accepted: source_id === 'fixture.cmdb_topology' ? 1 : 0,
      collapsed: 0,
      quarantined: 0,
      fixture_version: source_id === 'fixture.cmdb_topology' ? 'topology-1.2' : null,
    })),
    last_reset_at: lastResetAt,
  }
}

export const handlers = [
  http.get('*/api/v1/events', () => HttpResponse.json({
    generated_at: new Date().toISOString(),
    items: goldenEvents,
    next_cursor: null,
  })),
  http.get('*/api/v1/events/:eventId', ({ params }) => {
    const event = goldenEvents.find((item) => item.event_id === params.eventId)
    return event
      ? HttpResponse.json(event)
      : HttpResponse.json({ error: { code: 'EVENT_NOT_FOUND', message: 'Event not found.', details: [] } }, { status: 404 })
  }),
  http.get('*/api/v1/quarantine', () => HttpResponse.json({ items: [] })),
  http.get('*/api/v1/anomalies', () => HttpResponse.json({
    generated_at: new Date().toISOString(),
    items: scenarioState === 'completed' ? [{
      anomaly_id: 'ano_forwarded_rps_001',
      event_id: goldenEvents[0].event_id,
      entity_id: 'api-gateway-01',
      source: goldenEvents[0].source,
      anomaly_type: 'FORWARDED_TRAFFIC_SPIKE',
      severity: 0.95,
      score: 0.94,
      detector_id: 'rolling_zscore_v1',
      detected_at: '2026-07-14T09:30:30Z',
      context_only: false,
      can_open_incident: true,
      explanation: 'Forwarded traffic exceeded the rolling baseline.',
    }] : [],
  })),
  http.get('*/api/v1/simulator/scenarios', () => HttpResponse.json({
    generated_at: new Date().toISOString(),
    items: [
      { scenario_id: 'gateway_rate_limit_disabled', title: 'Gateway rate-limit disabled', description: 'Gateway configuration regression.', affected_entity_ids: ['api-gateway-01', 'checkout-api-01'], duration_seconds: 120, expected_signals: ['forwarded request spike'], difficulty: 'introductory', reference_datasets: [], transformation_version: 'synthetic-scenario-1.0', quality_flag: 'SYNTHETIC' },
      { scenario_id: 'network_path_congestion', title: 'Network-path degradation', description: 'Packet loss affects the checkout path.', affected_entity_ids: ['api-gateway-01', 'checkout-api-01'], duration_seconds: 75, expected_signals: ['packet loss', 'TCP retransmissions'], difficulty: 'advanced', reference_datasets: ['GAIA MicroSS', 'UNSW-NB15'], transformation_version: 'reference-scenario-builder-1.0', quality_flag: 'REFERENCE_DERIVED' },
      { scenario_id: 'ddos_syn_flood', title: 'DDoS / SYN flood', description: 'A traffic and SYN surge reaches the gateway.', affected_entity_ids: ['api-gateway-01', 'checkout-api-01'], duration_seconds: 90, expected_signals: ['ingress surge', 'SYN failures'], difficulty: 'advanced', reference_datasets: ['UNSW-NB15', 'NSL-KDD'], transformation_version: 'reference-scenario-builder-1.0', quality_flag: 'REFERENCE_DERIVED' },
      { scenario_id: 'gaia_resource_saturation', title: 'GAIA resource saturation', description: 'Payment service resources saturate.', affected_entity_ids: ['payment-api-01', 'checkout-api-01'], duration_seconds: 90, expected_signals: ['CPU saturation', 'memory saturation'], difficulty: 'intermediate', reference_datasets: ['GAIA MicroSS'], transformation_version: 'reference-scenario-builder-1.0', quality_flag: 'REFERENCE_DERIVED' },
      { scenario_id: 'port_scan_reconnaissance', title: 'Port scan / reconnaissance', description: 'A source probes many ports.', affected_entity_ids: ['api-gateway-01'], duration_seconds: 60, expected_signals: ['port fanout', 'connection rejection'], difficulty: 'intermediate', reference_datasets: ['UNSW-NB15', 'NSL-KDD'], transformation_version: 'reference-scenario-builder-1.0', quality_flag: 'REFERENCE_DERIVED' },
      { scenario_id: 'hdfs_datanode_failure', title: 'HDFS DataNode failure', description: 'A DataNode and its replicas degrade.', affected_entity_ids: ['datanode-01', 'namenode-01'], duration_seconds: 90, expected_signals: ['DataNode failure', 'replica degradation'], difficulty: 'advanced', reference_datasets: ['Loghub HDFS'], transformation_version: 'reference-scenario-builder-1.0', quality_flag: 'REFERENCE_DERIVED' },
      { scenario_id: 'trace_anomaly', title: 'Distributed trace anomaly', description: 'Trace latency and structure become anomalous.', affected_entity_ids: ['checkout-api-01', 'payment-api-01'], duration_seconds: 60, expected_signals: ['critical-path latency', 'missing parent span'], difficulty: 'advanced', reference_datasets: ['Sample traces'], transformation_version: 'reference-scenario-builder-1.0', quality_flag: 'REFERENCE_DERIVED' },
      { scenario_id: 'database_connection_pool_exhaustion', title: 'Database connection-pool exhaustion', description: 'The payment database pool saturates.', affected_entity_ids: ['payment-db-01', 'payment-api-01'], duration_seconds: 90, expected_signals: ['database utilization', 'pool waits'], difficulty: 'intermediate', reference_datasets: [], transformation_version: 'synthetic-scenario-1.0', quality_flag: 'SYNTHETIC' },
      { scenario_id: 'dns_resolution_failure', title: 'DNS resolution failure', description: 'Checkout DNS lookups fail.', affected_entity_ids: ['checkout-api-01', 'payment-api-01'], duration_seconds: 60, expected_signals: ['DNS resolver errors'], difficulty: 'intermediate', reference_datasets: [], transformation_version: 'synthetic-scenario-1.0', quality_flag: 'SYNTHETIC' },
      { scenario_id: 'tls_certificate_failure', title: 'TLS certificate failure', description: 'Payment TLS handshakes fail.', affected_entity_ids: ['payment-api-01', 'checkout-api-01'], duration_seconds: 60, expected_signals: ['TLS handshake failure'], difficulty: 'intermediate', reference_datasets: [], transformation_version: 'synthetic-scenario-1.0', quality_flag: 'SYNTHETIC' },
    ],
  })),
  http.get('*/api/v1/incidents', () => HttpResponse.json({ generated_at: new Date().toISOString(), items: [incident], next_cursor: null })),
  http.get('*/api/v1/incidents/:incidentId/investigation', ({ params }) =>
    params.incidentId === incident.incident_id
      ? HttpResponse.json({
          ...goldenInvestigationResponse,
          incident: mockReviews.some((review) => review.decision === 'confirmed')
            ? { ...incident, status: 'resolved', confirmed_hypothesis_id: mockReviews.find((review) => review.decision === 'confirmed')?.hypothesis_id }
            : incident,
          reviews: mockReviews,
        })
      : HttpResponse.json({ error: { code: 'INCIDENT_NOT_FOUND', message: 'Incident not found.', details: [] } }, { status: 404 }),
  ),
  http.get('*/api/v1/incidents/:incidentId/audit', () => HttpResponse.json({ generated_at: '2026-07-14T09:32:00Z', items: mockAudit, next_cursor: null })),
  http.get('*/api/v1/incidents/:incidentId', ({ params }) =>
    params.incidentId === incident.incident_id
      ? HttpResponse.json(incident)
      : HttpResponse.json({ error: { code: 'INCIDENT_NOT_FOUND', message: 'Incident not found.', details: [] } }, { status: 404 }),
  ),
  http.post('*/api/v1/incidents/:incidentId/review', async ({ request }) => {
    const body = await request.json() as Record<string, unknown>
    const review = {
      review_id: `mock_review_${mockReviews.length + 1}`,
      incident_id: incident.incident_id,
      analysis_run_id: body.analysis_run_id,
      hypothesis_id: body.hypothesis_id,
      decision: body.decision,
      client_action_id: body.client_action_id,
      requested_evidence_id: body.requested_evidence_id ?? null,
      reviewer: body.reviewer,
      comment: body.comment,
      created_at: new Date().toISOString(),
    }
    mockReviews = [...mockReviews, review]
    mockAudit = [...mockAudit, {
      audit_id: `aud_mock_${mockAudit.length + 1}`,
      timestamp: new Date().toISOString(),
      actor_type: 'user',
      actor_id: body.reviewer,
      action: body.decision === 'confirmed' ? 'REVIEW_CONFIRMED' : body.decision === 'rejected' ? 'REVIEW_REJECTED' : 'REVIEW_EVIDENCE_REQUESTED',
      object_type: 'hypothesis',
      object_id: body.hypothesis_id,
      request_id: body.client_action_id,
      analysis_run_id: body.analysis_run_id,
      payload: {},
    }]
    return HttpResponse.json({
      request_id: 'req_mock_review_001',
      generated_at: new Date().toISOString(),
      review,
    })
  }),
  http.post('*/api/v1/simulator/start', () => { simulatorState = 'ready'; scenarioState = 'baseline_complete'; return HttpResponse.json({ ...simulatorStatus(), request_id: 'req_mock_start' }) }),
  http.post('*/api/v1/simulator/stop', () => { simulatorState = 'stopped'; return HttpResponse.json({ ...simulatorStatus(), request_id: 'req_mock_stop' }) }),
  http.post('*/api/v1/simulator/reset', () => { simulatorState = 'stopped'; scenarioState = 'idle'; scenarioId = null; lastResetAt = new Date().toISOString(); mockReviews = []; mockAudit = []; return HttpResponse.json({ ...simulatorStatus(), request_id: 'req_mock_reset', reset_audit_id: 'aud_mock_reset' }) }),
  http.post('*/api/v1/simulator/scenarios/:scenarioId/trigger', ({ params }) => { simulatorState = 'completed'; scenarioState = 'completed'; scenarioId = String(params.scenarioId); return HttpResponse.json({ ...simulatorStatus(), request_id: 'req_mock_trigger' }) }),
  http.get('*/api/v1/simulator/status', () => HttpResponse.json(simulatorStatus())),
  http.get('*/api/v1/topology', () => HttpResponse.json(goldenInvestigationResponse.topology)),
  http.get('*/api/v1/topology/path', () =>
    HttpResponse.json({
      source: 'api-gateway-01',
      target: 'payment-db-01',
      relation_type: 'sends_traffic_to',
      direction: 'forward',
      distance: 3,
      entity_ids: ['api-gateway-01', 'checkout-api-01', 'payment-api-01', 'payment-db-01'],
    }),
  ),
  http.get('*/api/v1/topology/blast-radius/:entityId', ({ params }) =>
    HttpResponse.json({
      root_entity_id: params.entityId,
      mode: 'traffic',
      relation_type: 'sends_traffic_to',
      direction: 'forward',
      max_hops: 2,
      entity_ids: ['checkout-api-01', 'payment-api-01', 'auth-api-01'],
    }),
  ),
]
