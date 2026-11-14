import { Outlet } from 'react-router'
import { BrandMark } from './BrandMark'
import { PreferenceMenu } from './PreferenceMenu'
import { SiteFooter } from './SiteFooter'

/** Setup, sign-in and registration: the form alone under the site's name. */
export function AuthLayout() {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="flex h-(--topbar-height) items-center justify-between gap-2 px-4 md:px-8">
        <BrandMark />
        <PreferenceMenu />
      </header>
      <main id="main" className="flex flex-1 justify-center px-5 pt-6 pb-14 sm:items-center sm:pt-0 md:px-8">
        <Outlet />
      </main>
      <SiteFooter className="mx-5 mb-5 md:mx-8" />
    </div>
  )
}
