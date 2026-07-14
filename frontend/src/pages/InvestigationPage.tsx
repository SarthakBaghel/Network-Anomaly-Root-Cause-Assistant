import { Background, Controls, ReactFlow, type Edge, type Node } from '@xyflow/react'

import type { components } from '../contracts/openapi'
import investigationFixture from '../test-fixtures/golden-investigation-response.json'
import { TEST_IDS, hypothesisRowTestId } from '../test-fixtures/testid-manifest'

type InvestigationResponse = components['schemas']['InvestigationResponse']

const investigation = investigationFixture as unknown as InvestigationResponse
const nodes: Node[] = investigation.topology.nodes.map((node, index) => ({
  id: node.id,
  position: { x: (index % 3) * 220, y: Math.floor(index / 3) * 140 },
  data: { label: `${node.name} · ${node.state ?? 'normal'}` },
}))
const edges: Edge[] = investigation.topology.edges.map((edge, index) => ({
  id: `${edge.source}-${edge.target}-${edge.relation_type}-${index}`,
  source: edge.source,
  target: edge.target,
  label: edge.relation_type,
  type: 'smoothstep',
}))

export function InvestigationPage() {
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
        <ReactFlow nodes={nodes} edges={edges} fitView>
          <Background />
          <Controls />
        </ReactFlow>
      </section>
      <section className="flex gap-3">
        <button data-testid={TEST_IDS.hypothesisConfirm}>Confirm</button>
        <button data-testid={TEST_IDS.hypothesisReject}>Reject</button>
        <button data-testid={TEST_IDS.evidenceRequest}>Request evidence</button>
      </section>
      <section data-testid={TEST_IDS.auditTrailPanel}><h2>Audit trail</h2></section>
    </main>
  )
}

