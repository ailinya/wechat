import { useEffect } from 'react'
import './App.css'

import { AppShell } from './app/AppShell'
import { AuthProvider, useAuth } from './app/AuthContext'
import { LoginPage } from './app/LoginPage'
import { moduleByPath } from './app/modules'
import { navigate, useHashRoute } from './app/router'
import { Placeholder } from './features/Placeholder'

function Routes() {
  const { status, hasPermission } = useAuth()
  const route = useHashRoute()

  // Redirect as an effect rather than during render (safe under StrictMode).
  useEffect(() => {
    if (status === 'anonymous' && route.path !== '/login') {
      navigate('/login')
    } else if (status === 'authenticated' && route.path === '/login') {
      navigate('/dashboard')
    }
  }, [status, route.path])

  if (status === 'loading') {
    return (
      <div className="center-state" role="status">
        <span>正在恢复会话…</span>
      </div>
    )
  }

  if (route.path === '/login') {
    return status === 'authenticated' ? null : <LoginPage />
  }

  if (status === 'anonymous') {
    return null
  }

  const module = moduleByPath(route.path)
  if (!module) {
    return (
      <AppShell currentPath={route.path}>
        <section className="center-state">
          <h1>页面不存在</h1>
          <p>未找到对应的模块，请从左侧导航选择。</p>
        </section>
      </AppShell>
    )
  }

  const allowed = module.permission === null || hasPermission(module.permission)

  return (
    <AppShell currentPath={route.path}>
      {allowed ? (
        <Placeholder module={module} />
      ) : (
        <section className="center-state" role="alert">
          <h1>无访问权限</h1>
          <p>当前账号没有访问「{module.label}」所需的权限。</p>
        </section>
      )}
    </AppShell>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <Routes />
    </AuthProvider>
  )
}
