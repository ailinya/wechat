/** Pagination controls bound to the page/page_size query contract. */

interface Props {
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
  onPageSizeChange: (pageSize: number) => void
}

const PAGE_SIZE_OPTIONS = [10, 20, 50]

export function Pagination({ page, pageSize, total, onPageChange, onPageSizeChange }: Props) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1
  const to = Math.min(total, page * pageSize)

  return (
    <nav className="pagination" aria-label="分页" data-testid="pagination">
      <span className="pagination-summary">
        共 {total} 条 · 第 {page}/{totalPages} 页（{from}-{to}）
      </span>
      <button
        type="button"
        className="ghost-button"
        disabled={page <= 1}
        onClick={() => onPageChange(page - 1)}
      >
        上一页
      </button>
      <button
        type="button"
        className="ghost-button"
        disabled={page >= totalPages}
        onClick={() => onPageChange(page + 1)}
      >
        下一页
      </button>
      <label className="pagination-size">
        每页
        <select
          value={pageSize}
          onChange={(event) => onPageSizeChange(Number(event.target.value))}
        >
          {PAGE_SIZE_OPTIONS.map((size) => (
            <option key={size} value={size}>
              {size}
            </option>
          ))}
        </select>
        条
      </label>
    </nav>
  )
}
