interface Insets { top: number; bottom: number; left: number; right: number }

interface WebApp {
  initData: string
  colorScheme: 'light' | 'dark'
  themeParams?: { bg_color?: string }
  safeAreaInset?: Insets
  contentSafeAreaInset?: Insets
  ready(): void
  expand(): void
  onEvent(name: string, callback: () => void): void
  offEvent(name: string, callback: () => void): void
  BackButton?: { show(): void; hide(): void; onClick(fn: () => void): void; offClick(fn: () => void): void }
  HapticFeedback?: { notificationOccurred(kind: 'success' | 'error'): void }
  isVersionAtLeast?(version: string): boolean
  downloadFile?(params: { url: string; file_name: string }, callback: (started: boolean) => void): void
}

declare global { interface Window { Telegram?: { WebApp?: WebApp } } }

export const telegram = () => window.Telegram?.WebApp

export function applyTelegramTheme(mode: 'auto' | 'light' | 'dark') {
  const app = telegram()
  const dark = mode === 'dark' || (mode === 'auto' && (app?.colorScheme === 'dark'
    || (!app?.initData && window.matchMedia('(prefers-color-scheme: dark)').matches)))
  document.documentElement.classList.toggle('dark', dark)
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
  for (const side of ['top', 'bottom', 'left', 'right'] as const) {
    const inset = (app?.safeAreaInset?.[side] ?? 0) + (app?.contentSafeAreaInset?.[side] ?? 0)
    document.documentElement.style.setProperty(`--safe-${side}`, `${inset}px`)
  }
}

export function haptic(kind: 'success' | 'error') {
  const app = telegram()
  if (app?.isVersionAtLeast?.('6.1')) app.HapticFeedback?.notificationOccurred(kind)
}
