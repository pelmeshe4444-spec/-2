import { extname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { apiHandler } from '../functions/_shared/runtime.ts'
import { fixtures, testConfiguration } from './fixtures.ts'

await fixtures()
const api = apiHandler(testConfiguration)
const dist = fileURLToPath(new URL('../../frontend/dist/', import.meta.url))
const media: Record<string, string> = { '.js': 'text/javascript', '.css': 'text/css', '.woff2': 'font/woff2', '.html': 'text/html', '.svg': 'image/svg+xml' }
Deno.serve({ hostname: '127.0.0.1', port: 8109 }, async request => {
  const url = new URL(request.url)
  if (url.pathname.startsWith('/api/')) return await api(request)
  let path = resolve(dist, '.' + decodeURIComponent(url.pathname))
  if (!path.startsWith(resolve(dist))) return new Response(null, { status: 403 })
  try { if (!(await Deno.stat(path)).isFile) path = resolve(dist, 'index.html') } catch { path = resolve(dist, 'index.html') }
  return new Response(await Deno.readFile(path), { headers: { 'Content-Type': media[extname(path)] ?? 'application/octet-stream' } })
})
