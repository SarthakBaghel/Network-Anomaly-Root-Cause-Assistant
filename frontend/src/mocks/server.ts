import { setupServer } from 'msw/node'

import { handlers } from '../test-fixtures/handlers'

export const server = setupServer(...handlers)
