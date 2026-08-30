import type { ReactNode } from 'react'
import { Radar, TriangleAlert } from 'lucide-react'

/** The four states every async surface must have.
 *  A spinner alone is not a loading state, a blank panel is not an empty state,
 *  and "something went wrong" is not an error state. */

export function Skeleton({ rows = 4, className = '' }: { rows?: number; className?: string }) {
  return (
    <div className={`space-y-2 ${className}`} role="status" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="skeleton h-8"
          style={{ animationDelay: `${i * 90}ms`, opacity: 1 - i * 0.11 }}
        />
      ))}
      <span className="sr-only">Loading</span>
    </div>
  )
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string
  body: string
  action?: ReactNode
  icon?: string
}) {
  return (
    <div className="flex flex-col items-center justify-center text-center px-6 py-12 gap-3">
      <div aria-hidden className="text-dim">
        <Radar size={36} strokeWidth={1.2} />
      </div>
      <h3 className="font-display text-base text-ink">{title}</h3>
      <p className="text-sm text-muted max-w-md leading-relaxed">{body}</p>
      {action}
    </div>
  )
}

export function ErrorState({
  title = 'That request did not complete',
  error,
  onRetry,
}: {
  title?: string
  error: unknown
  onRetry?: () => void
}) {
  const message =
    error instanceof Error ? error.message : typeof error === 'string' ? error : 'Unknown error'
  return (
    <div className="panel p-5 border-coral/40" role="alert">
      <div className="flex items-start gap-3">
        <TriangleAlert aria-hidden className="text-coral shrink-0 mt-0.5" size={19} strokeWidth={1.7} />
        <div className="flex-1 min-w-0">
          <h3 className="font-display text-sm text-coral mb-1.5">{title}</h3>
          {/* The real reason, not a euphemism. */}
          <p className="text-xs text-muted font-mono break-words leading-relaxed">{message}</p>
          {onRetry && (
            <button
              onClick={onRetry}
              className="mt-3 px-3 py-1.5 text-xs font-mono tracking-wider border border-hairline
                         hover:border-radar hover:text-radar transition-colors"
            >
              RETRY
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export function ProgressRail({
  stage,
  progress,
  log,
}: {
  stage: string
  progress: number
  log?: string[]
}) {
  return (
    <div className="panel p-4" role="status" aria-live="polite">
      <div className="flex items-baseline justify-between mb-2">
        {/* A named stage, never an indeterminate bar. */}
        <span className="text-sm text-ink font-mono">{stage}</span>
        <span className="num text-xs text-radar">{Math.round(progress * 100)}%</span>
      </div>
      <div className="h-1 bg-hairline overflow-hidden">
        <div
          className="h-full bg-radar transition-all duration-500 ease-out"
          style={{ width: `${Math.max(2, progress * 100)}%` }}
        />
      </div>
      {log && log.length > 0 && (
        <ul className="mt-3 space-y-0.5 max-h-24 overflow-y-auto">
          {log.slice(-4).map((line, i) => (
            <li key={i} className="text-2xs text-dim font-mono truncate">{line.slice(0, 140)}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
