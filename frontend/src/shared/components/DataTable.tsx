/** Generic table renderer for list pages. */

export interface Column<T> {
  key: string
  header: string
  render?: (row: T) => React.ReactNode
}

interface Props<T> {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string
  caption?: string
  /** Optional leading checkbox column for bulk operations. */
  selection?: {
    checked: Set<string>
    onToggle: (key: string) => void
  }
  /** Optional trailing actions column, rendered per row. */
  actions?: (row: T) => React.ReactNode
}

export function DataTable<T>({ columns, rows, rowKey, caption, selection, actions }: Props<T>) {
  return (
    <div className="table-scroll">
    <table className="data-table" data-testid="data-table">
      {caption && <caption className="visually-hidden">{caption}</caption>}
      <thead>
        <tr>
          {selection && <th scope="col" aria-label="选择" />}
          {columns.map((column) => (
            <th key={column.key} scope="col">
              {column.header}
            </th>
          ))}
          {actions && <th scope="col">操作</th>}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={rowKey(row)}>
            {selection && (
              <td>
                <input
                  type="checkbox"
                  aria-label={`选择 ${rowKey(row)}`}
                  checked={selection.checked.has(rowKey(row))}
                  onChange={() => selection.onToggle(rowKey(row))}
                />
              </td>
            )}
            {columns.map((column) => (
              <td key={column.key}>
                {column.render ? column.render(row) : String((row as Record<string, unknown>)[column.key] ?? '')}
              </td>
            ))}
            {actions && <td>{actions(row)}</td>}
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  )
}
