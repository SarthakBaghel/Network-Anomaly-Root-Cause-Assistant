import { http, HttpResponse } from 'msw'

import investigation from './golden-investigation-response.json'

export const handlers = [
  http.get('*/api/v1/incidents/inc_001/investigation', () => HttpResponse.json(investigation)),
]

