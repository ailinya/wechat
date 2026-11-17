/** Authentication state and session lifecycle. */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { authApi } from '../shared/api/auth'
import { ApiError } from '../shared/api/client'
import type { CurrentUser, PermissionCode } from '../shared/api/types'

type AuthStatus = 'loading' | 'authenticated' | 'anonymous'

interface AuthContextValue {
  status: AuthStatus
  user: CurrentUser | null
  error: string | null
  login: (account: string, password: string) => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
  hasPermission: (code: PermissionCode) => boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('loading')
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const me = await authApi.me()
      setUser(me)
      setStatus('authenticated')
    } catch {
      setUser(null)
      setStatus('anonymous')
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const login = useCallback(async (account: string, password: string) => {
    setError(null)
    try {
      const result = await authApi.login(account, password)
      setUser(result.user)
      setStatus('authenticated')
    } catch (cause) {
      const message = cause instanceof ApiError ? cause.message : '登录失败'
      setError(message)
      throw cause
    }
  }, [])

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } finally {
      setUser(null)
      setStatus('anonymous')
      setError(null)
    }
  }, [])

  const hasPermission = useCallback(
    (code: PermissionCode) => Boolean(user?.permissions?.includes(code)),
    [user],
  )

  const value = useMemo<AuthContextValue>(
    () => ({ status, user, error, login, logout, refresh, hasPermission }),
    [status, user, error, login, logout, refresh, hasPermission],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
