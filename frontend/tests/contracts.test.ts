import { describe, expect, it } from 'vitest'

import { ROUTES } from '../src/routes'
import investigation from '../src/test-fixtures/golden-investigation-response.json'
import { TEST_IDS } from '../src/test-fixtures/testid-manifest'

describe('Milestone-0 frontend contracts', () => {
  it('freezes exactly the two P0 routes', () => {
    expect(Object.values(ROUTES)).toEqual(['/', '/incidents/:incidentId'])
  })

  it('loads a consistent investigation fixture', () => {
    expect(investigation.analysis_run_id).toBe('run_007')
    expect(investigation.incident.current_analysis_run_id).toBe('run_007')
    expect(investigation.hypotheses.map((item) => item.evidence_score)).toEqual([92.1, 65.6, 41.5])
  })

  it('keeps golden-path test IDs unique', () => {
    const values = Object.values(TEST_IDS)
    expect(new Set(values).size).toBe(values.length)
  })
})

