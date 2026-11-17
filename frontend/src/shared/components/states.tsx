/** Shared list page states: loading, empty, failure and no-permission. */

export type ListStatus = 'loading' | 'ready' | 'empty' | 'error' | 'forbidden'

interface StatesProps {
  status: ListStatus
  error?: string | null
  emptyText?: string
  onRetry?: () => void
}

/** Renders the four non-data states of a list view; returns null when data exists. */
export function ListStates({ status, error, emptyText = '暂无数据', onRetry }: StatesProps) {
  if (status === 'loading') {
    return (
      <div className="list-state" role="status" data-state="loading">
        <span>加载中…</span>
      </div>
    )
  }
  if (status === 'forbidden') {
    return (
      <div className="list-state" role="alert" data-state="forbidden">
        <h2>无访问权限</h2>
        <p>当前账号没有查看该列表所需的权限。</p>
      </div>
    )
  }
  if (status === 'error') {
    return (
      <div className="list-state" role="alert" data-state="error">
        <h2>加载失败</h2>
        <p>{error ?? '请求失败，请稍后重试'}</p>
        {onRetry && (
          <button type="button" className="ghost-button" onClick={onRetry}>
            重试
          </button>
        )}
      </div>
    )
  }
  if (status === 'empty') {
    return (
      <div className="list-state" role="status" data-state="empty">
        <span>{emptyText}</span>
      </div>
    )
  }
  return null
}
