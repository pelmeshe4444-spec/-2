import { strict as assert } from 'node:assert'
import type { Router } from '../functions/_shared/core.ts'
import { directoryRoutes } from '../functions/_shared/directory.ts'
import { attendanceRoutes } from '../functions/_shared/attendance.ts'
import { membershipRoutes } from '../functions/_shared/memberships.ts'
import { timetableRoutes } from '../functions/_shared/timetable.ts'
import { reportRoutes } from '../functions/_shared/reports.ts'
import { adminRoutes } from '../functions/_shared/admin.ts'
import { exportRoutes } from '../functions/_shared/exports.ts'
import legacy from './legacy-routes.json' with { type: 'json' }

const canonical = (path: string) => path.replace(/^\/api(?=\/)/, '').replace(/\{[^}]+\}|:[A-Za-z_]+/g, ':id')
export function migratedRoutes(): { method: string; path: string; module: string }[] {
  const routes: { method: string; path: string; module: string }[] = []
  for (const [module, register] of Object.entries({ directory: directoryRoutes, attendance: attendanceRoutes,
    memberships: membershipRoutes, timetable: timetableRoutes, reports: reportRoutes, admin: adminRoutes, exports: exportRoutes })) {
    register({ add(method: string, path: string) { routes.push({ method, path, module }) } } as unknown as Router)
  }
  for (const [method, path, module] of [['GET', '/health', 'runtime'], ['POST', '/telegram/webhook', 'webhook'],
    ['POST', '/internal/scheduler/run', 'scheduler-http'], ['GET', '/downloads/:key', 'exports'], ['HEAD', '/downloads/:key', 'exports']]) routes.push({ method, path, module })
  return routes
}
Deno.test('every discovered legacy FastAPI API route has a matching Edge method and path', () => {
  const actual = new Set(migratedRoutes().map(route => route.method + ' ' + canonical(route.path)))
  const missing = legacy.filter(route => !actual.has(route.method + ' ' + canonical(route.path)))
  assert.deepEqual(missing, [])
})
