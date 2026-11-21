export class HttpError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

const encoder = new TextEncoder()
export async function hmac(key: Uint8Array, text: string): Promise<Uint8Array> {
  const imported = await crypto.subtle.importKey('raw', new Uint8Array(key).buffer, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'])
  return new Uint8Array(await crypto.subtle.sign('HMAC', imported, encoder.encode(text)))
}
export function hex(bytes: Uint8Array): string {
  return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
}
export function equal(left: string, right: string): boolean {
  const a = encoder.encode(left), b = encoder.encode(right)
  let difference = a.length ^ b.length
  for (let index = 0; index < Math.max(a.length, b.length); index++) difference |= (a[index] ?? 0) ^ (b[index] ?? 0)
  return difference === 0
}
export interface Identity { id: number; username: string | null; name: string }
export async function authenticate(raw: string, token: string, ttl = 3600, now = Date.now() / 1000): Promise<Identity> {
  const denied = () => new HttpError(401, 'Откройте приложение заново из Telegram.')
  if (!raw || raw.length > 8192) throw denied()
  const fields = new URLSearchParams(raw)
  const entries = Array.from(fields)
  if (entries.length > 32 || new Set(entries.map(([name]) => name)).size !== entries.length ||
      entries.some(([name, value]) => !/^[a-z_]+$/.test(name) || value.includes('\n'))) throw denied()
  const supplied = fields.get('hash') ?? ''
  if (!/^[a-f0-9]{64}$/.test(supplied)) throw denied()
  fields.delete('hash')
  fields.sort()
  const key = await hmac(encoder.encode('WebAppData'), token)
  const expected = hex(await hmac(key, Array.from(fields, ([name, value]) => `${name}=${value}`).join('\n')))
  if (!equal(supplied, expected)) throw denied()
  const age = now - Number(fields.get('auth_date'))
  if (!Number.isFinite(age) || age < -30 || age > ttl) throw denied()
  try {
    const user = JSON.parse(fields.get('user') ?? '')
    if (!Number.isSafeInteger(user.id) || user.id <= 0 || user.id >= 2 ** 52 || user.is_bot ||
        typeof (user.first_name ?? '') !== 'string' || typeof (user.last_name ?? '') !== 'string' ||
        (user.username != null && typeof user.username !== 'string')) throw denied()
    return { id: user.id, username: user.username ?? null, name: [user.first_name, user.last_name].filter(Boolean).join(' ') }
  } catch { throw denied() }
}

export function internalSecret(supplied: string, expected: string): void {
  if (!expected || !equal(supplied, expected)) throw new HttpError(403, 'Доступ запрещён.')
}
