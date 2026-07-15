import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { anomaliesApi } from '../src/api/anomalies'
import { incidentsApi } from '../src/api/incidents'
import { simulatorApi } from '../src/api/simulator'
import { OverviewPage } from '../src/pages/OverviewPage'
import { TEST_IDS, anomalyRowTestId, incidentRowTestId, sourceHealthTestId } from '../src/test-fixtures/testid-manifest'
import { goldenInvestigationResponse } from '../src/test-fixtures/fixture-validation'

describe('OverviewPage live contracts', () => {
  afterEach(() => vi.restoreAllMocks())

  it('renders five source-health cards, live anomalies, and incidents from domain APIs', async () => {
    render(<OverviewPage />)

    expect(await screen.findByTestId(sourceHealthTestId('fixture.cmdb_topology'))).toHaveTextContent('ready')
    expect(await screen.findByTestId(incidentRowTestId('inc_001'))).toBeInTheDocument()
    expect(screen.getByText('Scenario not triggered')).toBeInTheDocument()
  })

  it('shows detector anomalies returned by the polling contract', async () => {
    vi.spyOn(anomaliesApi, 'list').mockResolvedValue({
      generated_at: '2026-07-14T09:31:00Z',
      items: [{
        anomaly_id: 'ano_ui_001',
        entity_id: 'api-gateway-01',
        anomaly_type: 'FORWARDED_TRAFFIC_SPIKE',
        score: 0.94,
        detector_id: 'rolling_zscore_v1',
        detected_at: '2026-07-14T09:30:30Z',
      }],
    })
    render(<OverviewPage />)
    expect(await screen.findByTestId(anomalyRowTestId('ano_ui_001'))).toHaveTextContent('94.0')
  })

  it('disables simulator controls while a trigger transition is in flight', async () => {
    let resolveTrigger: ((value: any) => void) | undefined
    vi.spyOn(simulatorApi, 'trigger').mockImplementation(() => new Promise((resolve) => { resolveTrigger = resolve }))
    vi.spyOn(incidentsApi, 'list').mockResolvedValue({ items: [goldenInvestigationResponse.incident], next_cursor: null } as any)
    render(<OverviewPage />)
    const trigger = await screen.findByTestId(TEST_IDS.scenarioTrigger)
    fireEvent.click(trigger)
    await waitFor(() => expect(trigger).toBeDisabled())
    resolveTrigger?.(await simulatorApi.status())
    await waitFor(() => expect(trigger).not.toBeDisabled())
  })

  it('renders the baseline-without-incident state from live contracts', async () => {
    const status = await simulatorApi.status()
    vi.spyOn(simulatorApi, 'status').mockResolvedValue({
      ...status,
      state: 'running',
      scenario_state: 'baseline',
      scenario_id: null,
    })
    vi.spyOn(anomaliesApi, 'list').mockResolvedValue({ generated_at: status.generated_at, items: [] })
    vi.spyOn(incidentsApi, 'list').mockResolvedValue({ items: [], next_cursor: null } as any)

    render(<OverviewPage />)

    expect(await screen.findByText('Baseline running; no incident has been triggered yet.')).toBeInTheDocument()
    expect(screen.getByText('Baseline running; no incident yet.')).toBeInTheDocument()
  })

  it('shows a quarantine warning from per-source counters', async () => {
    const status = await simulatorApi.status()
    vi.spyOn(simulatorApi, 'status').mockResolvedValue({
      ...status,
      source_health: status.source_health.map((source, index) =>
        index === 0 ? { ...source, quarantined: 2 } : source,
      ),
    })

    render(<OverviewPage />)

    expect(await screen.findByTestId(TEST_IDS.quarantineBanner)).toHaveTextContent('2 source records')
  })
})
