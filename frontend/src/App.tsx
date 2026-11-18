import { useEffect } from 'react'
import './App.css'

import { AppShell } from './app/AppShell'
import { AuthProvider, useAuth } from './app/AuthContext'
import { LoginPage } from './app/LoginPage'
import { moduleByPath } from './app/modules'
import { navigate, useHashRoute } from './app/router'
import { Placeholder } from './features/Placeholder'
import { CollectionPage } from './features/collection/CollectionPage'
import { CollectionSettings } from './features/collection/CollectionSettings'
import { MaterialsPage } from './features/materials/MaterialsPage'
import { DashboardHome } from './features/dashboard/Home'
import { JobPollingDemoPage } from './features/dashboard/JobPollingDemoPage'
import { ListDemoPage } from './features/dashboard/ListDemoPage'
import { UploadDemoPage } from './features/dashboard/UploadDemoPage'
import { FeedbackProvider } from './shared/components/feedback'

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

  const pageContent = (() => {
    if (!allowed) {
      return (
        <section className="center-state" role="alert">
          <h1>无访问权限</h1>
          <p>当前账号没有访问「{module.label}」所需的权限。</p>
        </section>
      )
    }
    if (route.path === '/dashboard/components-demo') {
      return <ListDemoPage />
    }
    if (route.path === '/dashboard/job-demo') {
      return <JobPollingDemoPage />
    }
    if (route.path === '/dashboard/upload-demo') {
      return <UploadDemoPage />
    }
    if (module.key === 'dashboard') {
      return <DashboardHome module={module} />
    }
    if (module.key === 'collection') {
      return <CollectionPage />
    }
    if (module.key === 'materials') {
      return <MaterialsPage />
    }
    if (module.key === 'settings') return <CollectionSettings />
    return <Placeholder module={module} />
  })()

  return <AppShell currentPath={route.path}>{pageContent}</AppShell>
}

export default function App() {
  return (
    <AuthProvider>
      <FeedbackProvider>
        <Routes />
      </FeedbackProvider>
    </AuthProvider>
  )
}
