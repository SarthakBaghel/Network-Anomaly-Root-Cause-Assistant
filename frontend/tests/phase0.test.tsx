import type { ReactNode } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { eventsApi } from '../src/api/events'
import { incidentsApi } from '../src/api/incidents'
import { simulatorApi } from '../src/api/simulator'
import { topologyApi } from '../src/api/topology'
import { shouldAcceptSnapshot } from '../src/hooks/usePolling'
import { InvestigationPage } from '../src/pages/InvestigationPage'
import { OverviewPage } from '../src/pages/OverviewPage'
import { goldenEvents, goldenInvestigationResponse } from '../src/test-fixtures/fixture-validation'
import {
  TEST_IDS,
  evidenceRequestTestId,
  hypothesisConfirmTestId,
  hypothesisRejectTestId,
  hypothesisRowTestId,
  incidentRowTestId,
  sourceHealthTestId,
} from '../src/test-fixtures/testid-manifest'

vi.mock('@xyflow/react', () => ({
  ReactFlow: ({ children }: { children: ReactNode }) => <div data-testid="react-flow-canvas">{children}</div>,
  Background: () => null,
  Controls: () => null,
}))

describe('Person 2 Phase 0', () => {
  it('loads P3 events and P5 investigation output through MSW and Axios', async () => {
    const [events, investigation, topology, simulator] = await Promise.all([
      eventsApi.list(),
      incidentsApi.getInvestigation('inc_001'),
      topologyApi.get('inc_001'),
      simulatorApi.status(),
    ])

    expect(events).toHaveLength(goldenEvents.length)
    expect(investigation.analysis_run_id).toBe(goldenInvestigationResponse.analysis_run_id)
    expect(topology.fixture_version).toBe(goldenInvestigationResponse.topology.fixture_version)
    expect(simulator.source_health).toHaveLength(5)
    expect(simulator.state).toBe('stopped')
  })

  it('renders the mocked investigation with all Phase 0 panels and controls', async () => {
    render(<InvestigationPage incidentId="inc_001" />)

    await screen.findByTestId(TEST_IDS.investigationPanel)
    expect(screen.getByTestId(TEST_IDS.evidencePanel)).toBeInTheDocument()
    expect(screen.getByTestId(TEST_IDS.timelinePanel)).toBeInTheDocument()
    expect(screen.getByTestId(TEST_IDS.topologyGraph)).toBeInTheDocument()
    expect(screen.getByTestId(TEST_IDS.auditTrailPanel)).toBeInTheDocument()
    expect(screen.getByTestId(hypothesisRowTestId('hyp_001'))).toHaveTextContent('92.1')
    expect(screen.getByTestId(hypothesisConfirmTestId('hyp_001'))).toBeInTheDocument()
    expect(screen.getByTestId(hypothesisRejectTestId('hyp_001'))).toBeInTheDocument()
    expect(screen.getByTestId(evidenceRequestTestId('hyp_001'))).toBeInTheDocument()
  })

  it('provides stable test IDs for every Phase 0 control', async () => {
    render(<OverviewPage />)

    expect(await screen.findByTestId(TEST_IDS.simulatorStart)).toBeInTheDocument()
    expect(screen.getByTestId(TEST_IDS.simulatorReset)).toBeInTheDocument()
    expect(screen.getByTestId(TEST_IDS.scenarioTrigger)).toBeInTheDocument()
    expect(await screen.findByTestId(incidentRowTestId('inc_001'))).toBeInTheDocument()
    expect(sourceHealthTestId('simulator.prometheus')).toBe('source-health-simulator.prometheus')
    expect(new Set(Object.values(TEST_IDS)).size).toBe(Object.values(TEST_IDS).length)
  })

  it('rejects an older poll and accepts a complete newer analysis snapshot', async () => {
    const current = Date.parse('2026-07-14T09:31:41.500Z')
    expect(shouldAcceptSnapshot(current, { generated_at: '2026-07-14T09:31:40.000Z', analysis_run_id: 'run_006' })).toBe(false)
    expect(shouldAcceptSnapshot(current, { generated_at: '2026-07-14T09:31:42.000Z', analysis_run_id: 'run_008' })).toBe(true)

    render(<InvestigationPage incidentId="inc_001" />)
    await waitFor(() => expect(screen.getByTestId(TEST_IDS.investigationPanel)).toBeInTheDocument())
  })
})
