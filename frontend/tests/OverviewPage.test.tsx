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

    expect(await screen.findByTestId(sourceHealthTestId('fixture.cmdb_topology'))).toHaveTextContent('healthy')
    expect(await screen.findByTestId(incidentRowTestId('inc_001'))).toBeInTheDocument()
    expect(screen.getByText('Reset data before running the baseline.')).toBeInTheDocument()
  })

  it('shows detector anomalies returned by the polling contract', async () => {
    vi.spyOn(anomaliesApi, 'list').mockResolvedValue({
      generated_at: '2026-07-14T09:31:00Z',
      items: [{
        anomaly_id: 'ano_ui_001',
        event_id: goldenInvestigationResponse.timeline[0].event.event_id,
        entity_id: 'api-gateway-01',
        source: goldenInvestigationResponse.timeline[0].event.source,
        anomaly_type: 'FORWARDED_TRAFFIC_SPIKE',
        severity: 0.95,
        score: 0.94,
        detector_id: 'rolling_zscore_v1',
        detected_at: '2026-07-14T09:30:30Z',
        context_only: false,
        can_open_incident: true,
        explanation: 'Forwarded traffic exceeded the rolling baseline.',
      }],
    })
    render(<OverviewPage />)
    expect(await screen.findByTestId(anomalyRowTestId('ano_ui_001'))).toHaveTextContent('94.0')
  })

  it('disables simulator controls while a trigger transition is in flight', async () => {
    let resolveTrigger: ((value: Awaited<ReturnType<typeof simulatorApi.trigger>>) => void) | undefined
    const status = await simulatorApi.status()
    vi.spyOn(simulatorApi, 'status').mockResolvedValue({
      ...status,
      state: 'ready',
      scenario_state: 'baseline_complete',
      scenario_id: null,
    })
    vi.spyOn(simulatorApi, 'trigger').mockImplementation(() => new Promise((resolve) => { resolveTrigger = resolve }))
    vi.spyOn(incidentsApi, 'list').mockResolvedValue({
      generated_at: '2026-07-14T09:31:00Z',
      items: [goldenInvestigationResponse.incident],
      next_cursor: null,
    })
    render(<OverviewPage />)
    const trigger = await screen.findByTestId(TEST_IDS.scenarioTrigger)
    const reset = await screen.findByTestId(TEST_IDS.simulatorReset)
    await waitFor(() => expect(trigger).not.toBeDisabled())
    fireEvent.click(trigger)
    await waitFor(() => expect(trigger).toBeDisabled())
    expect(trigger).toHaveTextContent('Generating RCA…')
    expect(screen.getByTestId(TEST_IDS.simulatorState)).toHaveTextContent('generating RCA')
    expect(screen.getByText('Processing scenario evidence and generating the RCA explanation…')).toBeInTheDocument()
    expect(reset).toBeDisabled()
    resolveTrigger?.({
      ...status,
      request_id: 'req_trigger_test',
      state: 'completed',
      scenario_state: 'completed',
      scenario_id: 'gateway-rate-limit-disabled',
    })
    await waitFor(() => expect(reset).not.toBeDisabled())
    expect(trigger).not.toBeDisabled()
  })

  it('renders the baseline-without-incident state from live contracts', async () => {
    const status = await simulatorApi.status()
    vi.spyOn(simulatorApi, 'status').mockResolvedValue({
      ...status,
      state: 'running',
      scenario_state: 'baseline',
      scenario_id: null,
      last_reset_at: '2026-07-14T09:25:00Z',
    })
    vi.spyOn(anomaliesApi, 'list').mockResolvedValue({ generated_at: status.generated_at, items: [] })
    vi.spyOn(incidentsApi, 'list').mockResolvedValue({ generated_at: status.generated_at, items: [], next_cursor: null })

    render(<OverviewPage />)

    expect(await screen.findByText(`Replaying baseline: ${status.baseline_ticks_emitted}/${status.baseline_ticks_required}`)).toBeInTheDocument()
    expect(screen.getByText('No current-run incident. Reset and run the baseline to begin.')).toBeInTheDocument()
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

  it('loads scenario choices from the backend catalogue', async () => {
    render(<OverviewPage />)

    const scenarioSelect = await screen.findByTestId(TEST_IDS.scenarioSelect)
    expect(scenarioSelect).toHaveTextContent('Database connection-pool exhaustion')
    expect(scenarioSelect).toHaveTextContent('Network-path degradation')
    expect(scenarioSelect).toHaveTextContent('DDoS / SYN flood')
    expect(scenarioSelect).toHaveTextContent('GAIA resource saturation')
    expect(scenarioSelect).toHaveTextContent('Port scan / reconnaissance')
    expect(scenarioSelect).toHaveTextContent('HDFS DataNode failure')
    expect(scenarioSelect).toHaveTextContent('Distributed trace anomaly')
    expect(scenarioSelect).toHaveTextContent('DNS resolution failure')
    expect(scenarioSelect).toHaveTextContent('TLS certificate failure')
  })

  it('requires reset confirmation before clearing current data', async () => {
    const resetSpy = vi.spyOn(simulatorApi, 'reset')
    render(<OverviewPage />)

    fireEvent.click(await screen.findByTestId(TEST_IDS.simulatorReset))
    expect(resetSpy).not.toHaveBeenCalled()
    fireEvent.click(screen.getByTestId(TEST_IDS.simulatorResetConfirm))
    await waitFor(() => expect(resetSpy).toHaveBeenCalledTimes(1))
  })
})
