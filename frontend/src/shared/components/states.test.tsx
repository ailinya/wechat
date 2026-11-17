import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ListStates } from './states'

describe('ListStates', () => {
  it('renders the loading state', () => {
    render(<ListStates status="loading" />)
    expect(screen.getByRole('status')).toHaveTextContent('加载中')
    expect(screen.getByRole('status').getAttribute('data-state')).toBe('loading')
  })

  it('renders the empty state with custom text', () => {
    render(<ListStates status="empty" emptyText="没有符合条件的记录" />)
    expect(screen.getByRole('status')).toHaveTextContent('没有符合条件的记录')
  })

  it('renders the error state with retry', () => {
    render(<ListStates status="error" error="服务器开小差了" onRetry={() => {}} />)
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('加载失败')
    expect(alert).toHaveTextContent('服务器开小差了')
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument()
  })

  it('renders the no-permission state', () => {
    render(<ListStates status="forbidden" />)
    expect(screen.getByRole('alert')).toHaveTextContent('无访问权限')
  })

  it('renders nothing in the ready state', () => {
    const { container } = render(<ListStates status="ready" />)
    expect(container.querySelector('.list-state')).toBeNull()
  })
})
