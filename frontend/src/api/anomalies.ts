import { request, type JsonResponse } from './client'

export const anomaliesApi = {
  list: (limit = 20, signal?: AbortSignal) =>
    request<JsonResponse<'list_anomalies_api_v1_anomalies_get'>>({
      method: 'GET',
      url: '/anomalies',
      params: { limit },
      signal,
    }),
}
