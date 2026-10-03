import { render, screen } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { vi, describe, expect, it } from 'vitest'
import { App } from './App'

vi.mock('./lib/api', () => ({
  getHealth: vi.fn().mockResolvedValue({ status: 'ok', service: 'DBZenith', version: '0.7.0' }),
}))

describe('DBZenith application shell', () => {
  it('renders dashboard navigation and heading', () => {
    render(<BrowserRouter><App /></BrowserRouter>)
    expect(screen.getByText('DBZenith')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Dashboard' })).toBeInTheDocument()
  })
})
