import axios, { AxiosError, type AxiosRequestConfig } from 'axios'

import type { components, operations } from '../contracts/openapi'

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 5_000,
  headers: { Accept: 'application/json' },
})

export type JsonResponse<OperationId extends keyof operations> = operations[OperationId] extends {
  responses: { 200: { content: { 'application/json': infer Body } } }
}
  ? Body
  : never

export type JsonRequest<OperationId extends keyof operations> = operations[OperationId] extends {
  requestBody: { content: { 'application/json': infer Body } }
}
  ? Body
  : never

export type ApiErrorPayload = components['schemas']['ErrorBody']
type ApiErrorDetail = components['schemas']['ErrorDetail']

export class ApiClientError extends Error {
  readonly status: number | undefined
  readonly payload: ApiErrorPayload

  constructor(status: number | undefined, payload: ApiErrorPayload) {
    super(payload.message)
    this.name = 'ApiClientError'
    this.status = status
    this.payload = payload
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isErrorDetail(value: unknown): value is ApiErrorDetail {
  return isRecord(value)
    && typeof value.reason_code === 'string'
    && (value.field === undefined || value.field === null || typeof value.field === 'string')
}

function toErrorPayload(value: unknown): ApiErrorPayload | null {
  const envelope = isRecord(value) && isRecord(value.error) ? value.error : null
  if (!isRecord(envelope) || typeof envelope.code !== 'string' || typeof envelope.message !== 'string') {
    return null
  }
  return {
    code: envelope.code,
    message: envelope.message,
    details: Array.isArray(envelope.details) ? envelope.details.filter(isErrorDetail) : [],
  }
}

function normalizeError(error: unknown): ApiClientError {
  if (error instanceof ApiClientError) {
    return error
  }
  if (error instanceof AxiosError) {
    const payload = toErrorPayload(error.response?.data)
    return new ApiClientError(
      error.response?.status,
      payload ?? {
        code: error.code ?? 'NETWORK_ERROR',
        message: error.message || 'The request could not be completed.',
        details: [],
      },
    )
  }
  return new ApiClientError(undefined, {
    code: 'UNEXPECTED_ERROR',
    message: 'The request could not be completed.',
    details: [],
  })
}

export async function request<Response>(config: AxiosRequestConfig): Promise<Response> {
  try {
    const response = await apiClient.request<Response>(config)
    return response.data
  } catch (error) {
    throw normalizeError(error)
  }
}
