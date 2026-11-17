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
}

export function DataTable<T>({ columns, rows, rowKey, caption }: Props<T>) {
  return (
    <table className="data-table" data-testid="data-table">
      {caption && <caption className="visually-hidden">{caption}</caption>}
      <thead>
        <tr>
          {columns.map((column) => (
            <th key={column.key} scope="col">
              {column.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={rowKey(row)}>
            {columns.map((column) => (
              <td key={column.key}>
                {column.render ? column.render(row) : String((row as Record<string, unknown>)[column.key] ?? '')}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
