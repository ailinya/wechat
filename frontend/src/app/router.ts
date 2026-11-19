/** Minimal hash-based router that keeps query context in the URL. */

import { useEffect, useState } from 'react'

let navigationGuard: (() => boolean) | null = null
export function setNavigationGuard(guard: (() => boolean) | null) { navigationGuard = guard }

export interface Route {
  path: string
  query: URLSearchParams
}

function parseHash(): Route {
  const raw = window.location.hash.replace(/^#/, '') || '/login'
  const [path, search = ''] = raw.split('?')
  return { path: path || '/login', query: new URLSearchParams(search) }
}

export function useHashRoute(): Route {
  const [route, setRoute] = useState<Route>(parseHash)

  useEffect(() => {
    let previousHash = window.location.hash
    const onChange = () => {
      if (navigationGuard && !navigationGuard()) {
        window.history.replaceState(null, '', window.location.pathname + window.location.search + previousHash)
        return
      }
      previousHash = window.location.hash
      setRoute(parseHash())
    }
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])

  return route
}

export function navigate(path: string, query?: URLSearchParams): void {
  const search = query ? `?${query.toString()}` : ''
  window.location.hash = `${path}${search}`
}
