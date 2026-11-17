/** Minimal hash-based router that keeps query context in the URL. */

import { useEffect, useState } from 'react'

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
    const onChange = () => setRoute(parseHash())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])

  return route
}

export function navigate(path: string, query?: URLSearchParams): void {
  const search = query ? `?${query.toString()}` : ''
  window.location.hash = `${path}${search}`
}
