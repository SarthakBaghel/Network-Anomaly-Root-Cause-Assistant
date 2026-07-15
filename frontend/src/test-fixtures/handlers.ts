import { http, HttpResponse } from 'msw'

import { goldenEvents, goldenInvestigationResponse } from './fixture-validation'

const incident = goldenInvestigationResponse.incident

export const handlers = [
  http.get('*/api/v1/events', () => HttpResponse.json(goldenEvents)),
  http.get('*/api/v1/events/:eventId', ({ params }) => {
    const event = goldenEvents.find((item) => item.event_id === params.eventId)
    return event
      ? HttpResponse.json(event)
      : HttpResponse.json({ error: { code: 'EVENT_NOT_FOUND', message: 'Event not found.', details: [] } }, { status: 404 })
  }),
  http.get('*/api/v1/quarantine', () => HttpResponse.json({ items: [] })),
  http.get('*/api/v1/incidents', () => HttpResponse.json({ items: [incident] })),
  http.get('*/api/v1/incidents/:incidentId/investigation', ({ params }) =>
    params.incidentId === incident.incident_id
      ? HttpResponse.json(goldenInvestigationResponse)
      : HttpResponse.json({ error: { code: 'INCIDENT_NOT_FOUND', message: 'Incident not found.', details: [] } }, { status: 404 }),
  ),
  http.get('*/api/v1/incidents/:incidentId/audit', () => HttpResponse.json([])),
  http.get('*/api/v1/incidents/:incidentId', ({ params }) =>
    params.incidentId === incident.incident_id
      ? HttpResponse.json(incident)
      : HttpResponse.json({ error: { code: 'INCIDENT_NOT_FOUND', message: 'Incident not found.', details: [] } }, { status: 404 }),
  ),
  http.post('*/api/v1/incidents/:incidentId/review', () =>
    HttpResponse.json({
      review_id: 'mock_review_001',
      incident_id: incident.incident_id,
      analysis_run_id: goldenInvestigationResponse.analysis_run_id,
      hypothesis_id: 'hyp_001',
      decision: 'confirmed',
      client_action_id: 'mock-client-action',
      requested_evidence_id: null,
      reviewer: 'mock-operator',
      comment: 'Mock review accepted.',
      created_at: goldenInvestigationResponse.generated_at,
    }),
  ),
  http.post('*/api/v1/simulator/start', () => HttpResponse.json({ status: 'running' })),
  http.post('*/api/v1/simulator/stop', () => HttpResponse.json({ status: 'stopped' })),
  http.post('*/api/v1/simulator/reset', () => HttpResponse.json({ status: 'reset' })),
  http.post('*/api/v1/simulator/scenarios/:scenarioId/trigger', () => HttpResponse.json({ status: 'triggered' })),
  http.get('*/api/v1/simulator/status', () => HttpResponse.json({ status: 'ready' })),
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
