import type { components } from '../contracts/openapi'

import rawGoldenEvents from './golden-events.json'
import rawInvestigationResponse from './golden-investigation-response.json'

type CanonicalEvent = components['schemas']['CanonicalEvent']
export type InvestigationResponse = components['schemas']['InvestigationResponse']

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function requireRecord(value: unknown, label: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error(`${label} must be an object`)
  }
  return value
}

function requireString(value: unknown, label: string): asserts value is string {
  if (typeof value !== 'string' || value.length === 0) {
    throw new Error(`${label} must be a non-empty string`)
  }
}

function requireArray(value: unknown, label: string): asserts value is unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`${label} must be an array`)
  }
}

function assertCanonicalEvent(value: unknown, label: string): asserts value is CanonicalEvent {
  const event = requireRecord(value, label)
  for (const field of ['event_id', 'entity_id', 'event_type', 'timestamp', 'ingested_at', 'source', 'schema_version']) {
    requireString(event[field], `${label}.${field}`)
  }
  if (!['metric', 'log', 'alert', 'config_change'].includes(String(event.modality))) {
    throw new Error(`${label}.modality must be a generated Modality value`)
  }
  if (typeof event.severity !== 'number') {
    throw new Error(`${label}.severity must be a number`)
  }
}

export function assertInvestigationResponse(value: unknown): asserts value is InvestigationResponse {
  const response = requireRecord(value, 'investigation response')
  requireString(response.analysis_run_id, 'investigation response.analysis_run_id')
  requireString(response.generated_at, 'investigation response.generated_at')

  const analysisRun = requireRecord(response.analysis_run, 'investigation response.analysis_run')
  requireString(analysisRun.analysis_run_id, 'investigation response.analysis_run.analysis_run_id')
  if (analysisRun.analysis_run_id !== response.analysis_run_id) {
    throw new Error('investigation response analysis run does not match its envelope')
  }

  const incident = requireRecord(response.incident, 'investigation response.incident')
  requireString(incident.incident_id, 'investigation response.incident.incident_id')
  if (incident.current_analysis_run_id !== response.analysis_run_id) {
    throw new Error('investigation response incident does not point to its analysis run')
  }

  requireArray(response.hypotheses, 'investigation response.hypotheses')
  for (const [index, hypothesis] of response.hypotheses.entries()) {
    const candidate = requireRecord(hypothesis, `hypotheses[${index}]`)
    requireString(candidate.hypothesis_id, `hypotheses[${index}].hypothesis_id`)
    requireString(candidate.analysis_run_id, `hypotheses[${index}].analysis_run_id`)
    if (candidate.analysis_run_id !== response.analysis_run_id || typeof candidate.evidence_score !== 'number') {
      throw new Error(`hypotheses[${index}] is not a valid generated Hypothesis`)
    }
  }

  const topology = requireRecord(response.topology, 'investigation response.topology')
  requireString(topology.fixture_version, 'investigation response.topology.fixture_version')
  requireArray(topology.nodes, 'investigation response.topology.nodes')
  requireArray(topology.edges, 'investigation response.topology.edges')
  for (const [index, node] of topology.nodes.entries()) {
    const record = requireRecord(node, `topology.nodes[${index}]`)
    requireString(record.id, `topology.nodes[${index}].id`)
    requireString(record.type, `topology.nodes[${index}].type`)
  }
  for (const [index, edge] of topology.edges.entries()) {
    const record = requireRecord(edge, `topology.edges[${index}]`)
    requireString(record.source, `topology.edges[${index}].source`)
    requireString(record.target, `topology.edges[${index}].target`)
    if (!['depends_on', 'sends_traffic_to'].includes(String(record.relation_type))) {
      throw new Error(`topology.edges[${index}].relation_type is invalid`)
    }
  }

  requireArray(response.timeline, 'investigation response.timeline')
  for (const [index, item] of response.timeline.entries()) {
    const timelineItem = requireRecord(item, `timeline[${index}]`)
    assertCanonicalEvent(timelineItem.event, `timeline[${index}].event`)
  }

  for (const field of ['evidence_by_hypothesis', 'recommendations_by_hypothesis'] as const) {
    requireRecord(response[field], `investigation response.${field}`)
  }
  requireRecord(response.explanation, 'investigation response.explanation')
  requireArray(response.reviews, 'investigation response.reviews')
}

export function assertGoldenEvents(value: unknown): asserts value is CanonicalEvent[] {
  requireArray(value, 'golden events')
  if (value.length === 0) {
    throw new Error('golden events must not be empty')
  }
  value.forEach((event, index) => assertCanonicalEvent(event, `golden events[${index}]`))
}

assertInvestigationResponse(rawInvestigationResponse)
assertGoldenEvents(rawGoldenEvents)

export const goldenInvestigationResponse: InvestigationResponse = rawInvestigationResponse
export const goldenEvents: CanonicalEvent[] = rawGoldenEvents
