import * as Dialog from '@radix-ui/react-dialog'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { clsx, type ClassValue } from 'clsx'
import { AlertCircle, Check, ChevronLeft, ChevronRight, ClipboardList, LoaderCircle, X } from 'lucide-react'
import { createContext, useContext, useState, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router'
import { twMerge } from 'tailwind-merge'
import { ApiError, api } from './api'
import { statuses } from './domain'
import { haptic } from './telegram'
import type { Me, SchoolClass } from './types'

export const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs))

const button = cva('button', { variants: { variant: { primary: 'primary', outline: 'outline', ghost: 'ghost', danger: 'danger' }, size: { normal: '', small: 'small', icon: 'icon-only' } }, defaultVariants: { variant: 'primary', size: 'normal' } })
export function Button({ className, variant, size, asChild, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof button> & { asChild?: boolean }) {
  const Element = asChild ? Slot : 'button'
  return <Element className={cn(button({ variant, size }), className)} {...props} />
}

export function Modal({ open, onOpenChange, title, description, children }: { open: boolean; onOpenChange(value: boolean): void; title: string; description?: string; children: ReactNode }) {
  return <Dialog.Root open={open} onOpenChange={onOpenChange}>
    <Dialog.Portal><Dialog.Overlay className="dialog-overlay" /><Dialog.Content className="dialog" {...(description ? {} : { 'aria-describedby': undefined })}>
      <div className="dialog-heading"><Dialog.Title>{title}</Dialog.Title><Dialog.Close asChild><Button size="icon" variant="ghost" aria-label="Закрыть"><X size={20} /></Button></Dialog.Close></div>
      {description && <Dialog.Description className="muted">{description}</Dialog.Description>}{children}
    </Dialog.Content></Dialog.Portal>
  </Dialog.Root>
}

export function Confirm({ title, text, label, onClose, onConfirm, busy }: { title: string; text: string; label: string; onClose(): void; onConfirm(): void; busy?: boolean }) {
  return <Modal open onOpenChange={open => !open && onClose()} title={title} description={text}>
    <div className="dialog-actions"><Button variant="outline" onClick={onClose}>Отмена</Button><Button onClick={onConfirm} disabled={busy}>{label}</Button></div>
  </Modal>
}

export function PageTitle({ title, subtitle, children }: { title: string; subtitle?: string; children?: ReactNode }) {
  return <div className="page-title"><div><h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div>{children && <div className="page-actions">{children}</div>}</div>
}
export function Panel({ title, children, subtitle, actions, className }: { title?: string; children: ReactNode; subtitle?: string; actions?: ReactNode; className?: string }) {
  return <section className={cn('panel', className)}>{title && <div className="panel-head"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{actions}</div>}{children}</section>
}
export function Empty({ title = 'Пока здесь пусто', description }: { title?: string; description?: string }) {
  return <div className="empty"><span><ClipboardList size={24} /></span><strong>{title}</strong>{description && <p>{description}</p>}</div>
}
export function Pending() { return <div className="empty" role="status"><LoaderCircle className="animate-spin" size={22} /> Загрузка…</div> }
export function Failure({ error, retry }: { error: Error; retry?: () => void }) {
  return <div className="failure" role="alert"><AlertCircle size={19} /><span>{error.message}</span>{retry && <Button size="small" variant="outline" onClick={retry}>Повторить</Button>}</div>
}
export function Notice({ text, error }: { text: string; error?: boolean }) {
  return <div role={error ? 'alert' : 'status'} className={cn('toast', error && 'toast-error')}>{error ? <AlertCircle size={19}/> : <Check size={19}/>} {text}</div>
}
export function StatusBadge({ status }: { status: number }) {
  const { icon: Icon, color, short } = statuses[status]
  return <span className={`badge badge-${color}`}><Icon size={13} />{short}</span>
}
export function ClassSelect({ items, value, change, label = 'Класс' }: { items: SchoolClass[]; value: number; change(value: number): void; label?: string }) {
  return <label className="inline-field"><span>{label}</span><select aria-label={label} value={value} onChange={event => change(Number(event.target.value))}>
    {items.length === 0 && <option value={0}>Нет классов</option>}{items.map(item => <option key={item.id} value={item.id}>{item.name}{!item.active ? ' · архив' : ''}</option>)}
  </select></label>
}
export function Pagination({ page, size, count, change }: { page: number; size: number; count: number; change(value: number): void }) {
  if (count <= size) return null
  return <div className="pagination"><span>{page * size + 1}–{Math.min(count, (page + 1) * size)} из {count}</span><div>
    <Button variant="outline" size="icon" disabled={page === 0} aria-label="Предыдущая страница" onClick={() => change(page - 1)}><ChevronLeft size={17} /></Button>
    <Button variant="outline" size="icon" disabled={(page + 1) * size >= count} aria-label="Следующая страница" onClick={() => change(page + 1)}><ChevronRight size={17} /></Button>
  </div></div>
}

export const Session = createContext<Me>(null!)
export const useSession = () => useContext(Session)
export const Toast = createContext<(message: string, error?: boolean) => void>(() => {})

export function useClass(items: SchoolClass[]) {
  const [params, setParams] = useSearchParams()
  const preferred = Number(params.get('class') || sessionStorage.getItem('attendance-class'))
  const value = items.some(item => item.id === preferred) ? preferred : (items[0]?.id ?? 0)
  const change = (id: number) => {
    sessionStorage.setItem('attendance-class', String(id))
    setParams(previous => { const next = new URLSearchParams(previous); next.set('class', String(id)); return next }, { replace: true })
  }
  return { value, change }
}

export function useData<T>(path: string | null, interval?: number) {
  return useQuery({ queryKey: [path], queryFn: () => api<T>(path!), enabled: Boolean(path), refetchInterval: interval })
}

export function useAction() {
  const [busy, setBusy] = useState(false)
  const notify = useContext(Toast)
  const client = useQueryClient()
  async function run<T>(action: () => Promise<T>, success?: string | ((result: T) => string)) {
    setBusy(true)
    try {
      const result = await action()
      if (success) {
        await client.invalidateQueries()
        notify(typeof success === 'string' ? success : success(result))
        haptic('success')
      }
      return result
    } catch (error) {
      if (error instanceof ApiError && [403, 409].includes(error.status)) client.invalidateQueries()
      notify(error instanceof Error ? error.message : 'Действие не выполнено.', true)
      haptic('error')
      return undefined
    } finally { setBusy(false) }
  }
  return { busy, run }
}
