import type { DataMode } from '@/lib/types'

const MODE_STYLE: Record<string, { bg: string; fg: string; border: string; title: string }> = {
  LIVE:      { bg: 'rgba(145,216,158,.10)', fg: '#91D89E', border: 'rgba(145,216,158,.44)',
               title: 'Fetched from the live source for this request.' },
  CACHED:    { bg: 'rgba(103,247,212,.08)', fg: '#67F7D4', border: 'rgba(103,247,212,.38)',
               title: 'Replayed from a previous identical request held on disk.' },
  FIXTURE:   { bg: 'rgba(255,176,0,.10)',  fg: '#FFB000', border: 'rgba(255,176,0,.42)',
               title: 'Bundled data recorded earlier, used because the live source was unavailable.' },
  SYNTHETIC: { bg: 'rgba(255,92,53,.12)',  fg: '#FF5C35', border: 'rgba(255,92,53,.48)',
               title: 'Generated data. Not an observation of the real world.' },
  DOWN:      { bg: 'rgba(255,92,53,.16)',  fg: '#FF5C35', border: 'rgba(255,92,53,.55)',
               title: 'This source could not be reached.' },
}

/** Data-mode badge.
 *  Present on every panel that shows data, without exception. An analyst must
 *  never have to ask whether what they are looking at came from a satellite or
 *  from a file we shipped. */
export function ModeBadge({ mode, label }: { mode: DataMode | string; label?: string }) {
  const style = MODE_STYLE[mode] ?? MODE_STYLE.DOWN
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-1 text-2xs font-mono font-semibold tracking-[0.1em] border"
      style={{ background: style.bg, color: style.fg, borderColor: style.border }}
      title={style.title}
      data-testid={`mode-badge-${mode}`}
    >
      <span aria-hidden className="w-1 h-1" style={{ background: style.fg }} />
      {label ?? mode}
    </span>
  )
}

const STATUS_STYLE: Record<string, string> = {
  NEW: 'text-sodium border-sodium/40 bg-sodium/10',
  IN_REVIEW: 'text-radar border-radar/40 bg-radar/10',
  ATTRIBUTED: 'text-coral border-coral/45 bg-coral/10',
  NO_ATTRIBUTION: 'text-muted border-muted/40 bg-muted/10',
  DISMISSED: 'text-dim border-dim/40 bg-dim/10',
  GATED: 'text-muted border-muted/40 bg-muted/10',
}

export function StatusPill({ status }: { status: string }) {
  return (
    <span
      className={`inline-block px-2 py-0.5 text-2xs font-mono tracking-[0.1em] border ${
        STATUS_STYLE[status] ?? STATUS_STYLE.DISMISSED
      }`}
    >
      {status.replace(/_/g, ' ')}
    </span>
  )
}
