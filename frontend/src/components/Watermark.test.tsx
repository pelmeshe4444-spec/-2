// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, test } from 'vitest'
import { Watermark } from './Watermark'

afterEach(cleanup)

test('renders the exact Attendance watermark once', () => {
  render(<Watermark />)
  expect(screen.getByText('made by @Pelmeshe4444').className).toBe('attendance-watermark')
})
