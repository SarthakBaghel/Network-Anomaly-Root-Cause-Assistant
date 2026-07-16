import { request, type JsonRequest, type JsonResponse } from "./client";

export const ASSISTANT_QUERY_TIMEOUT_MS = 35_000;

export const assistantApi = {
  query: (
    body: JsonRequest<"query_network_concepts_assistant">,
    signal?: AbortSignal,
  ) =>
    request<JsonResponse<"query_network_concepts_assistant">>({
      method: "POST",
      url: "/assistant/query",
      data: body,
      signal,
      timeout: ASSISTANT_QUERY_TIMEOUT_MS,
    }),
};
