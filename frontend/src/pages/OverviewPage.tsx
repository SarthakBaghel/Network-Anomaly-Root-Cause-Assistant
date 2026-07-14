import { TEST_IDS, incidentRowTestId } from '../test-fixtures/testid-manifest'

export function OverviewPage() {
  return (
    <main className="mx-auto max-w-6xl space-y-6 p-8">
      <header>
        <p className="text-sm font-semibold uppercase tracking-widest text-red-600">Operations</p>
        <h1 className="text-3xl font-bold">Network Anomaly RCA</h1>
      </header>
      <section className="flex gap-3">
        <button data-testid={TEST_IDS.simulatorStart}>Start baseline</button>
        <button data-testid={TEST_IDS.simulatorStop}>Stop</button>
        <button data-testid={TEST_IDS.simulatorReset}>Reset</button>
        <button data-testid={TEST_IDS.scenarioTrigger}>Trigger golden scenario</button>
      </section>
      <section data-testid={TEST_IDS.incidentList}>
        <h2 className="text-xl font-semibold">Incidents</h2>
        <a data-testid={incidentRowTestId('inc_001')} href="/incidents/inc_001">
          Checkout degradation through API gateway
        </a>
      </section>
    </main>
  )
}

