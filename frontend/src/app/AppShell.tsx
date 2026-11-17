/** Authenticated layout: eight-module navigation, user state and actions. */

import type { ReactNode } from 'react'

import { navigate } from './router'
import { useAuth } from './AuthContext'
import { MODULES } from './modules'

interface Props {
  currentPath: string
  children: ReactNode
}

export function AppShell({ currentPath, children }: Props) {
  const { user, logout, refresh } = useAuth()

  async function handleLogout() {
    await logout()
    navigate('/login')
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="brand-mark" aria-hidden="true">智</span>
          <span>智媒助手</span>
        </div>
        <nav aria-label="主导航">
          {MODULES.map((module) => {
            const active = currentPath === module.path || currentPath.startsWith(`${module.path}/`)
            const allowed = module.permission === null || Boolean(user?.permissions?.includes(module.permission))
            return (
              <button
                key={module.key}
                type="button"
                className={`nav-item${active ? ' active' : ''}${allowed ? '' : ' locked'}`}
                aria-current={active ? 'page' : undefined}
                title={allowed ? module.description : '当前账号无访问权限'}
                onClick={() => allowed && navigate(module.path)}
              >
                <span>{module.label}</span>
                {!allowed && <span className="nav-lock">无权限</span>}
              </button>
            )
          })}
        </nav>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div className="topbar-user">
            <span className="user-name">{user?.name}</span>
            <span className="user-account">@{user?.account}</span>
            <span className="user-roles">{user?.roles?.join('、') || '无角色'}</span>
          </div>
          <div className="topbar-actions">
            <button type="button" className="ghost-button" onClick={() => void refresh()}>
              刷新权限
            </button>
            <button type="button" className="ghost-button" onClick={() => void handleLogout()}>
              退出登录
            </button>
          </div>
        </header>
        <main className="content">{children}</main>
      </div>
    </div>
  )
}
