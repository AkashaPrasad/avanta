import type { ReactNode } from 'react'
import { ModeBadge } from './Badge'

export function Panel({
  title,
  mode,
  actions,
  children,
  className = '',
  dense = false,
}: {
  title?: string
  mode?: string
  actions?: ReactNode
  children: ReactNode
  className?: string
  dense?: boolean
}) {
  return (
    <section className={`panel flex flex-col min-h-0 ${className}`}>
      {(title || mode || actions) && (
        <header className="flex items-center gap-3 px-3 py-2 border-b hair shrink-0">
          {title && <h2 className="label flex-1 truncate">{title}</h2>}
          {mode && <ModeBadge mode={mode} />}
          {actions}
        </header>
      )}
      <div className={`${dense ? 'p-2' : 'p-3'} flex-1 min-h-0 overflow-auto`}>{children}</div>
    </section>
  )
}

export function Stat({
  label,
  value,
  unit,
  hint,
  tone = 'ink',
}: {
  label: string
  value: ReactNode
  unit?: string
  hint?: string
  tone?: 'ink' | 'radar' | 'coral' | 'sodium' | 'muted'
}) {
  const colour = {
    ink: 'text-ink', radar: 'text-radar', coral: 'text-coral',
    sodium: 'text-sodium', muted: 'text-muted',
  }[tone]
  return (
    <div title={hint}>
      <div className="label mb-1">{label}</div>
      <div className={`num text-lg leading-none ${colour}`}>
        {value}
        {unit && <span className="text-xs text-dim ml-1">{unit}</span>}
      </div>
    </div>
  )
}
