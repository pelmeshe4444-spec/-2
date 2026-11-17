import { telegram } from './telegram'

export const apiOrigin = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/+$/, '') ?? ''

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

async function request(path: string, method = 'GET', data?: unknown) {
  const initData = telegram()?.initData
  const response = await fetch(`${apiOrigin}/api/v1${path}`, {
    method, headers: { ...(initData ? { Authorization: `tma ${initData}` } : {}), ...(data === undefined ? {} : { 'Content-Type': 'application/json' }) },
    body: data === undefined ? undefined : JSON.stringify(data), cache: 'no-store',
  })
  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new ApiError(response.status, error?.detail ?? 'Сервер временно недоступен.')
  }
  return response
}

export async function api<T>(path: string, method = 'GET', data?: unknown): Promise<T> {
  return (await request(path, method, data)).json()
}

export async function download(path: string, name: string) {
  const app = telegram()
  if (app?.downloadFile && app.isVersionAtLeast?.('8.0') && location.protocol === 'https:') {
    const file = await api<{ path: string; name: string }>(`${path}${path.includes('?') ? '&' : '?'}ticket=true`)
    const url = new URL(file.path, apiOrigin || location.origin).href
    app.downloadFile({ url, file_name: file.name }, () => {})
    return
  }
  const url = URL.createObjectURL(await (await request(path)).blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  anchor.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 30000)
}
