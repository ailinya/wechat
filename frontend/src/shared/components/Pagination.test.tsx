import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { Pagination } from './Pagination'

describe('Pagination', () => {
  it('shows totals and disables previous on the first page', () => {
    render(
      <Pagination page={1} pageSize={10} total={35} onPageChange={() => {}} onPageSizeChange={() => {}} />,
    )
    expect(screen.getByTestId('pagination')).toHaveTextContent('共 35 条')
    expect(screen.getByText('上一页')).toHaveProperty('disabled', true)
    expect(screen.getByText('下一页')).toHaveProperty('disabled', false)
  })

  it('reports page and page-size changes', () => {
    const onPageChange = vi.fn()
    const onPageSizeChange = vi.fn()
    render(
      <Pagination page={2} pageSize={10} total={35} onPageChange={onPageChange} onPageSizeChange={onPageSizeChange} />,
    )
    screen.getByText('下一页').click()
    expect(onPageChange).toHaveBeenCalledWith(3)
    const select = screen.getByRole('combobox') as HTMLSelectElement
    select.value = '20'
    select.dispatchEvent(new Event('change', { bubbles: true }))
    expect(onPageSizeChange).toHaveBeenCalledWith(20)
  })
})
