import { Background, ReactFlow, type Edge, type Node } from '@xyflow/react'
import { useCallback, useMemo, useState } from 'react'

import { incidentsApi } from '../api/incidents'
import { type ApiClientError } from '../api/client'
import { usePolling } from '../hooks/usePolling'
import { assertInvestigationResponse, type InvestigationResponse } from '../test-fixtures/fixture-validation'
import { TEST_IDS, hypothesisRowTestId } from '../test-fixtures/testid-manifest'

type ReviewDecision = 'confirmed' | 'rejected' | 'evidence_requested'

function graphFromInvestigation(investigation: InvestigationResponse): { nodes: Node[]; edges: Edge[] } {
  return {
    nodes: investigation.topology.nodes.map((node, index) => ({
      id: node.id,
      position: { x: (index % 3) * 220, y: Math.floor(index / 3) * 140 },
      data: { label: `${node.name} · ${node.state ?? 'normal'}` },
    })),
    edges: investigation.topology.edges.map((edge, index) => ({
      id: `${edge.source}-${edge.target}-${edge.relation_type}-${index}`,
      source: edge.source,
      target: edge.target,
      label: edge.relation_type,
      type: 'smoothstep',
    })),
  }
}

export function InvestigationPage({ incidentId }: { incidentId: string }) {
  const loadInvestigation = useCallback(async () => {
    const response = await incidentsApi.getInvestigation(incidentId)
    assertInvestigationResponse(response)
    return response
  }, [incidentId])
  const { data: investigation, error, isLoading } = usePolling(loadInvestigation)
  const [reviewMessage, setReviewMessage] = useState<string | null>(null)

  const graph = useMemo(
    () => (investigation ? graphFromInvestigation(investigation) : { nodes: [], edges: [] }),
    [investigation],
  )

  const submitReview = async (decision: ReviewDecision) => {
    if (!investigation) return
    const missingEvidence = Object.values(investigation.evidence_by_hypothesis)
      .flat()
      .find((item) => item.kind === 'missing')
    await incidentsApi.submitReview(incidentId, {
      analysis_run_id: investigation.analysis_run_id,
      hypothesis_id: investigation.hypotheses[0].hypothesis_id,
      decision,
      client_action_id: `ui-${decision}-${investigation.analysis_run_id}`,
      reviewer: 'demo-operator',
      comment: 'Mock UI action submitted.',
      requested_evidence_id: decision === 'evidence_requested' ? missingEvidence?.evidence_id ?? null : null,
    })
    setReviewMessage(`Mock ${decision.replace('_', ' ')} action submitted.`)
  }

  if (isLoading && !investigation) {
    return <main className="p-8" data-testid={TEST_IDS.apiLoading}>Loading investigation…</main>
  }
  if (error || !investigation) {
    const message = (error as ApiClientError | null)?.message ?? 'Investigation is unavailable.'
    return <main className="p-8" data-testid={TEST_IDS.apiError} role="alert">{message}</main>
  }

  return (
    <main data-testid={TEST_IDS.investigationPanel} className="mx-auto max-w-7xl space-y-6 p-8">
      <header>
        <p className="text-sm text-slate-500">Analysis run {investigation.analysis_run_id}</p>
        <h1 className="text-3xl font-bold">{investigation.incident.title}</h1>
        <p>Probable root cause — awaiting human review</p>
      </header>
      <section>
        <h2 className="text-xl font-semibold">Ranked hypotheses</h2>
        {investigation.hypotheses.map((hypothesis) => (
          <article key={hypothesis.hypothesis_id} data-testid={hypothesisRowTestId(hypothesis.hypothesis_id)}>
            #{hypothesis.rank} {hypothesis.hypothesis_type}: {hypothesis.evidence_score} Evidence score
          </article>
        ))}
      </section>
      <section data-testid={TEST_IDS.evidencePanel}>
        <h2 className="text-xl font-semibold">Evidence</h2>
        {Object.values(investigation.evidence_by_hypothesis).flat().map((item) => (
          <p key={item.evidence_id}><strong>{item.kind}</strong>: {item.statement}</p>
        ))}
      </section>
      <section data-testid={TEST_IDS.timelinePanel}>
        <h2 className="text-xl font-semibold">Timeline</h2>
        <p>{investigation.timeline.length} evaluated events</p>
      </section>
      <section data-testid={TEST_IDS.topologyGraph} className="h-[420px] rounded border">
        <ReactFlow nodes={graph.nodes} edges={graph.edges} fitView>
          <Background />
        </ReactFlow>
      </section>
      <section className="flex gap-3">
        <button data-testid={TEST_IDS.hypothesisConfirm} onClick={() => void submitReview('confirmed')}>Confirm</button>
        <button data-testid={TEST_IDS.hypothesisReject} onClick={() => void submitReview('rejected')}>Reject</button>
        <button data-testid={TEST_IDS.evidenceRequest} onClick={() => void submitReview('evidence_requested')}>Request evidence</button>
      </section>
      {reviewMessage ? <p aria-live="polite">{reviewMessage}</p> : null}
      <section data-testid={TEST_IDS.auditTrailPanel}><h2>Audit trail</h2></section>
    </main>
  )
}
