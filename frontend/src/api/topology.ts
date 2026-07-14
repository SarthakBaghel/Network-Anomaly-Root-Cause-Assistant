import type { components } from '../contracts/openapi'
import { request, type JsonResponse } from './client'

type TopologyRelation = components['schemas']['TopologyRelation']

export const topologyApi = {
  get: (incidentId?: string) =>
    request<JsonResponse<'topology_api_v1_topology_get'>>({
      method: 'GET',
      url: '/topology',
      params: incidentId ? { incident_id: incidentId } : undefined,
    }),
  getPath: (source: string, target: string, relationType: TopologyRelation, direction: 'forward' | 'reverse') =>
    request<JsonResponse<'path_api_v1_topology_path_get'>>({
      method: 'GET',
      url: '/topology/path',
      params: { source, target, relation_type: relationType, direction },
    }),
  getBlastRadius: (entityId: string, mode: 'dependency' | 'traffic', maxHops?: number) =>
    request<JsonResponse<'blast_radius_api_v1_topology_blast_radius__entity_id__get'>>({
      method: 'GET',
      url: `/topology/blast-radius/${encodeURIComponent(entityId)}`,
      params: { mode, ...(maxHops === undefined ? {} : { max_hops: maxHops }) },
    }),
}
