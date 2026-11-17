/** Demo page for the shared list conventions (task 1.8).
 *
 * Shows the four states (loading/empty/error/no-permission), URL-backed
 * filters and pagination, and API-driven operation feedback.
 */

import { useState } from 'react'

import { useHashRoute } from '../../app/router'
import type { UserOut } from '../../shared/api/types'
import { DataTable, type Column } from '../../shared/components/DataTable'
import { Pagination } from '../../shared/components/Pagination'
import { ListStates } from '../../shared/components/states'
import { useListView } from '../../shared/components/useListView'
import { useUrlQuery } from '../../shared/components/useUrlQuery'

const columns: Column<UserOut>[] = [
  { key: 'account', header: '账号' },
  { key: 'name', header: '姓名' },
  { key: 'status', header: '状态' },
  {
    key: 'roles',
    header: '角色',
    render: (row) => row.roles?.map((role) => role.name).join('、') || '—',
  },
]

const STATUS_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'active', label: '启用' },
  { value: 'disabled', label: '停用' },
]

export function ListDemoPage() {
  const route = useHashRoute()
  const patchQuery = useUrlQuery(route.path, route.query)
  const page = Math.max(1, Number(route.query.get('page')) || 1)
  const pageSize = Math.min(100, Math.max(1, Number(route.query.get('page_size')) || 10))
  const keyword = route.query.get('keyword') ?? ''
  const status = route.query.get('status') ?? ''
  const [keywordDraft, setKeywordDraft] = useState(keyword)

  const view = useListView<UserOut>('/users', {
    page,
    pageSize,
    params: { keyword: keyword || undefined, status: status || undefined },
  })

  return (
    <section className="list-page" aria-label="共享列表组件演示">
      <h1>共享列表组件演示</h1>
      <p className="list-page-note">
        演示表格分页、筛选与四类状态。筛选和分页写入 URL，刷新或分享后可恢复。
        该页读取用户列表接口，无 user:read 权限的账号会看到「无权限」状态。
      </p>

      <form
        className="list-filters"
        onSubmit={(event) => {
          event.preventDefault()
          patchQuery({ keyword: keywordDraft || null, page: null })
        }}
      >
        <input
          type="search"
          aria-label="关键词筛选"
          placeholder="按账号或姓名搜索"
          value={keywordDraft}
          onChange={(event) => setKeywordDraft(event.target.value)}
        />
        <select
          aria-label="状态筛选"
          value={status}
          onChange={(event) => patchQuery({ status: event.target.value || null, page: null })}
        >
          {STATUS_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <button type="submit" className="primary-button">
          筛选
        </button>
      </form>

      {view.status === 'ready' && view.data && (
        <>
          <DataTable columns={columns} rows={view.data.items} rowKey={(row) => row.id} caption="用户列表" />
          <Pagination
            page={view.data.page}
            pageSize={view.data.page_size}
            total={view.data.total}
            onPageChange={(next) => patchQuery({ page: next === 1 ? null : next })}
            onPageSizeChange={(next) => patchQuery({ page_size: next === 10 ? null : next, page: null })}
          />
        </>
      )}
      <ListStates
        status={view.status}
        error={view.error}
        emptyText="没有符合筛选条件的记录"
        onRetry={view.status === 'error' ? view.retry : undefined}
      />
    </section>
  )
}
