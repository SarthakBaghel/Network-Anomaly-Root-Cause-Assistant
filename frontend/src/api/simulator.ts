import { request, type JsonResponse } from './client'

export const simulatorApi = {
  start: () => request<JsonResponse<'start_api_v1_simulator_start_post'>>({ method: 'POST', url: '/simulator/start' }),
  stop: () => request<JsonResponse<'stop_api_v1_simulator_stop_post'>>({ method: 'POST', url: '/simulator/stop' }),
  reset: () => request<JsonResponse<'reset_api_v1_simulator_reset_post'>>({ method: 'POST', url: '/simulator/reset' }),
  trigger: (scenarioId: string) =>
    request<JsonResponse<'trigger_api_v1_simulator_scenarios__scenario_id__trigger_post'>>({
      method: 'POST',
      url: `/simulator/scenarios/${encodeURIComponent(scenarioId)}/trigger`,
    }),
  status: (signal?: AbortSignal) => request<JsonResponse<'status_api_v1_simulator_status_get'>>({ method: 'GET', url: '/simulator/status', signal }),
}
