import { describe, expect, it } from 'vitest'
import { attendanceRate, formatTime, toDay } from './domain'

describe('Attendance calculations', () => {
  it('includes unmarked pupils in attendance rate', () => {
    expect(attendanceRate([2, 3, 1, 0, 0])).toBe(50)
    expect(attendanceRate([0, 0, 0, 0, 0])).toBe(0)
  })
  it('keeps calendar dates stable through month and year boundaries', () => {
    expect(toDay('2026-01-01', -1)).toBe('2025-12-31')
    expect(formatTime('2026-11-16T03:30:00Z', 'Asia/Tashkent')).toBe('08:30')
  })
})
