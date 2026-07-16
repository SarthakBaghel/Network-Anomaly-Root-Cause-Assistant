import { request, type JsonResponse } from './client'

// Scenario execution includes RCA persistence and, in LLM mode, up to two
// local Ollama attempts. Keep the normal API timeout strict while allowing
// this explicitly long-running mutation enough time to finish.
export const SCENARIO_TRIGGER_TIMEOUT_MS = 120_000

export const simulatorApi = {
  start: () => request<JsonResponse<'start_api_v1_simulator_start_post'>>({ method: 'POST', url: '/simulator/start' }),
  stop: () => request<JsonResponse<'stop_api_v1_simulator_stop_post'>>({ method: 'POST', url: '/simulator/stop' }),
  reset: () => request<JsonResponse<'reset_api_v1_simulator_reset_post'>>({ method: 'POST', url: '/simulator/reset' }),
  trigger: (scenarioId: string) =>
    request<JsonResponse<'trigger_api_v1_simulator_scenarios__scenario_id__trigger_post'>>({
      method: 'POST',
      url: `/simulator/scenarios/${encodeURIComponent(scenarioId)}/trigger`,
      timeout: SCENARIO_TRIGGER_TIMEOUT_MS,
    }),
  listScenarios: (signal?: AbortSignal) =>
    request<JsonResponse<'scenarios_api_v1_simulator_scenarios_get'>>({
      method: 'GET',
      url: '/simulator/scenarios',
      signal,
    }),
  status: (signal?: AbortSignal) => request<JsonResponse<'status_api_v1_simulator_status_get'>>({ method: 'GET', url: '/simulator/status', signal }),
}
