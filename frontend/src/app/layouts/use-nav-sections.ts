import { useAudience, useAuthStatus, useSession } from '@/shared/api'
import { navSections, type NavSection } from './navigation'

/** The navigation as this viewer sees it now: by their permissions, the site's audience and the features it shows. */
export function useNavSections(): NavSection[] {
  const current = useSession()
  const audience = useAudience()
  const status = useAuthStatus()
  return navSections({
    permissions: current.status === 'signedIn' ? current.user.permissions : [],
    audience: audience.data,
    visibilities: status.data?.features,
  })
}
