import type { Feature, Schemas, Visibilities } from '@/shared/api'
import openapi from '@/shared/api/openapi.json'

/** Every feature of the contract. */
export const FEATURES = openapi.components.schemas.Feature.enum as Feature[]

/** GET /v1/auth/status of a site past its setup that shows every feature to everyone, but for the ones named here. */
export function siteShowing(hidden: Visibilities = {}): Schemas['AuthStatusResponse'] {
  return {
    needs_first_administrator: false,
    registration_open: true,
    google_sign_in: false,
    features: { ...Object.fromEntries(FEATURES.map((feature) => [feature, 'everyone'])), ...hidden },
  }
}

export const OPEN_SITE = siteShowing()
