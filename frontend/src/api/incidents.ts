import { request, type JsonRequest, type JsonResponse } from './client'

export const incidentsApi = {
  list: (signal?: AbortSignal) => request<JsonResponse<'list_incidents_api_v1_incidents_get'>>({ method: 'GET', url: '/incidents', signal }),
  get: (incidentId: string) =>
    request<JsonResponse<'incident_summary_api_v1_incidents__incident_id__get'>>({
      method: 'GET',
      url: `/incidents/${encodeURIComponent(incidentId)}`,
    }),
  getInvestigation: (incidentId: string, signal?: AbortSignal) =>
    request<JsonResponse<'investigation_api_v1_incidents__incident_id__investigation_get'>>({
      method: 'GET',
      url: `/incidents/${encodeURIComponent(incidentId)}/investigation`,
      signal,
    }),
  submitReview: (
    incidentId: string,
    body: JsonRequest<'review_api_v1_incidents__incident_id__review_post'>,
  ) =>
    request<JsonResponse<'review_api_v1_incidents__incident_id__review_post'>>({
      method: 'POST',
      url: `/incidents/${encodeURIComponent(incidentId)}/review`,
      data: body,
    }),
  getAudit: (incidentId: string, signal?: AbortSignal) =>
    request<JsonResponse<'audit_api_v1_incidents__incident_id__audit_get'>>({
      method: 'GET',
      url: `/incidents/${encodeURIComponent(incidentId)}/audit`,
      signal,
    }),
}
