/** Login form. Credentials go only to the backend; no token is stored in JS. */

import { useState, type FormEvent } from 'react'

import { useAuth } from './AuthContext'
import { navigate } from './router'

export function LoginPage() {
  const { login, error } = useAuth()
  const [account, setAccount] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!account.trim() || !password) {
      setLocalError('请输入账号和密码')
      return
    }
    setLocalError(null)
    setSubmitting(true)
    try {
      await login(account.trim(), password)
      navigate('/dashboard')
    } catch {
      // error is surfaced by AuthContext
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="login-page">
      <form className="login-card" onSubmit={handleSubmit}>
        <div className="login-brand">
          <span className="brand-mark" aria-hidden="true">智</span>
          <span>智媒助手</span>
        </div>
        <h1>登录</h1>
        <p className="login-subtitle">请使用平台账号登录</p>

        <label className="field">
          <span>账号</span>
          <input
            name="account"
            autoComplete="username"
            value={account}
            onChange={(e) => setAccount(e.target.value)}
            disabled={submitting}
          />
        </label>
        <label className="field">
          <span>密码</span>
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={submitting}
          />
        </label>

        {(localError || error) && (
          <p className="form-error" role="alert">{localError || error}</p>
        )}

        <button className="primary-button" type="submit" disabled={submitting}>
          {submitting ? '登录中…' : '登录'}
        </button>
      </form>
    </main>
  )
}
