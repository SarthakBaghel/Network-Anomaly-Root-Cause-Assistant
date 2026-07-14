export const ROUTES = {
  overview: '/',
  investigation: '/incidents/:incidentId',
} as const

export type RouteName = keyof typeof ROUTES

