import { readFile } from 'node:fs/promises'

const fixture = JSON.parse(
  await readFile(new URL('../src/test-fixtures/golden-investigation-response.json', import.meta.url), 'utf8'),
)

if (fixture.analysis_run_id !== fixture.incident.current_analysis_run_id) {
  throw new Error('investigation mock mixes analysis runs')
}
if (fixture.hypotheses.map((item) => item.evidence_score).join(',') !== '92.1,65.6,41.5') {
  throw new Error('investigation mock does not contain the frozen evidence scores')
}
console.log('frontend contract fixture is consistent')

