/** Read and patch the query string of the current hash route. */

import { useCallback } from 'react'

import { navigate } from '../../app/router'

/** Patch query params; null/undefined/'' values are dropped so the URL stays clean. */
export function useUrlQuery(currentPath: string, currentQuery: URLSearchParams) {
  return useCallback(
    (patch: Record<string, string | number | null | undefined>) => {
      const next = new URLSearchParams(currentQuery.toString())
      for (const [key, value] of Object.entries(patch)) {
        if (value === null || value === undefined || value === '') {
          next.delete(key)
        } else {
          next.set(key, String(value))
        }
      }
      navigate(currentPath, next)
    },
    [currentPath, currentQuery],
  )
}
