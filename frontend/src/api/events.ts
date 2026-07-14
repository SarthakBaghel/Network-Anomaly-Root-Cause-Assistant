import type { components } from '../contracts/openapi'
import { request, type JsonResponse } from './client'

export type CanonicalEvent = components['schemas']['CanonicalEvent']

export const eventsApi = {
  list: () => request<JsonResponse<'list_events_api_v1_events_get'>>({ method: 'GET', url: '/events' }),
  get: (eventId: string) =>
    request<JsonResponse<'get_event_api_v1_events__event_id__get'>>({
      method: 'GET',
      url: `/events/${encodeURIComponent(eventId)}`,
    }),
  listQuarantine: () =>
    request<JsonResponse<'list_quarantine_api_v1_quarantine_get'>>({
      method: 'GET',
      url: '/quarantine',
    }),
}
