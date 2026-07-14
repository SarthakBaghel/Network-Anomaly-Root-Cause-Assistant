import { setupWorker } from 'msw/browser'

import { handlers } from '../test-fixtures/handlers'

const worker = setupWorker(...handlers)

export async function startMockWorker(): Promise<void> {
  await worker.start({
    onUnhandledRequest: 'bypass',
    serviceWorker: { url: '/mockServiceWorker.js' },
  })
}
