import { useState } from 'react'

import { simulatorApi } from '../api/simulator'
import { TEST_IDS, incidentRowTestId } from '../test-fixtures/testid-manifest'

export function OverviewPage() {
  const [message, setMessage] = useState<string | null>(null)
  const runAction = async (action: () => Promise<unknown>, label: string) => {
    await action()
    setMessage(`${label} request accepted.`)
  }

  return (
    <main className="mx-auto max-w-6xl space-y-6 p-8">
      <header>
        <p className="text-sm font-semibold uppercase tracking-widest text-red-600">Operations</p>
        <h1 className="text-3xl font-bold">Network Anomaly RCA</h1>
      </header>
      <section className="flex gap-3">
        <button data-testid={TEST_IDS.simulatorStart} onClick={() => void runAction(simulatorApi.start, 'Start')}>Start baseline</button>
        <button data-testid={TEST_IDS.simulatorStop} onClick={() => void runAction(simulatorApi.stop, 'Stop')}>Stop</button>
        <button data-testid={TEST_IDS.simulatorReset} onClick={() => void runAction(simulatorApi.reset, 'Reset')}>Reset</button>
        <button data-testid={TEST_IDS.scenarioTrigger} onClick={() => void runAction(() => simulatorApi.trigger('gateway_rate_limit_disabled'), 'Scenario trigger')}>Trigger golden scenario</button>
      </section>
      {message ? <p aria-live="polite">{message}</p> : null}
      <section data-testid={TEST_IDS.incidentList}>
        <h2 className="text-xl font-semibold">Incidents</h2>
        <a data-testid={incidentRowTestId('inc_001')} href="/incidents/inc_001">
          Checkout degradation through API gateway
        </a>
      </section>
    </main>
  )
}
