import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Button } from '@/components/primitives/Button'
import { ErrorState, Skeleton } from '@/components/primitives/States'
import { titleise } from '@/lib/format'

const NOT_AVAILABLE = 'NOT AVAILABLE'

export function Dossier() {
  const { runId = '', mmsi = '' } = useParams()
  const [copied, setCopied] = useState(false)

  const dossier = useQuery({
    queryKey: ['dossier', runId, mmsi],
    queryFn: () => api.dossier({ run_id: runId, mmsi }),
    enabled: !!runId && !!mmsi,
    retry: 0,
  })

  const handoff = useMutation({
    mutationFn: () => api.handoff({ run_id: runId, mmsi }),
  })

  if (dossier.isLoading) return <div className="p-6 max-w-4xl"><Skeleton rows={8} /></div>
  if (dossier.isError) {
    return (
      <div className="p-6 max-w-2xl">
        <ErrorState title="The dossier could not be generated" error={dossier.error}
                    onRetry={() => dossier.refetch()} />
      </div>
    )
  }

  const fields = dossier.data?.fields ?? {}

  return (
    <div className="record-page flex-1 min-h-0 overflow-y-auto">
      <div className="record-page__inner max-w-4xl mx-auto p-6">
        <header className="record-hero mb-6">
          <h1>
            MARPOL Annex I, Appendix 3 — evidence dossier
          </h1>
          <p className="text-xs text-muted leading-relaxed max-w-2xl">
            Laid out field by field against the itemised list of evidence in Appendix 3, because
            that is the form a referral to a flag State has to take. Any field the analysis could
            not establish is printed as <span className="text-coral font-mono">{NOT_AVAILABLE}</span>
            {' '}rather than left blank — a blank reads as an oversight, an explicit gap tells the
            officer what still has to be collected.
          </p>
        </header>

        <div className="record-toolbar flex flex-wrap gap-2 mb-6 sticky top-0 py-3 z-10 -mx-1 px-1">
          <a href={api.dossierPdfUrl(runId, mmsi)} target="_blank" rel="noreferrer"
             data-testid="download-pdf"
             className="px-3 py-2 text-xs font-mono tracking-[0.1em] uppercase border border-radar/50
                        text-radar hover:bg-radar/15 transition-colors">
            DOWNLOAD PDF
          </a>
          <a href={api.dossierJsonUrl(runId, mmsi)} target="_blank" rel="noreferrer"
             className="px-3 py-2 text-xs font-mono tracking-[0.1em] uppercase border hair
                        text-muted hover:text-ink hover:border-muted transition-colors">
            DOWNLOAD JSON
          </a>
          <Button
            variant="ghost"
            onClick={() => {
              navigator.clipboard?.writeText(JSON.stringify(dossier.data?.fields, null, 2))
              setCopied(true)
              window.setTimeout(() => setCopied(false), 2000)
            }}
          >
            {copied ? 'COPIED' : 'COPY MANIFEST'}
          </Button>
          <Button variant="ghost" onClick={() => handoff.mutate()} disabled={handoff.isPending}>
            {handoff.isPending ? 'BUILDING…' : 'OOSA HANDOFF'}
          </Button>
        </div>

        {handoff.isError && (
          <div className="mb-6"><ErrorState error={handoff.error} /></div>
        )}
        {handoff.data && (
          <section className="panel p-5 mb-6 border-radar/30" data-testid="oosa-handoff">
            <h2 className="font-display text-sm text-radar mb-2">
              INCOIS OOSA / NOAA GNOME release specification
            </h2>
            <p className="text-xs text-muted mb-3 leading-relaxed">
              INCOIS already forecasts where oil goes — OOSA v4.0, built on GNOME, operational
              since 2014 over 60–100°E, 0–25°N, and the Coast Guard is trained on it. What it
              cannot do is start without a release point and time, which in a routine discharge
              nobody has. This is that input. {handoff.data.domain_check?.message}
            </p>
            {/* Focusable and named: a scrolling region a keyboard user cannot
                reach is a region they cannot read. */}
            <pre tabIndex={0} role="region" aria-label="OOSA release specification, JSON"
                 className="text-2xs font-mono text-muted bg-abyss p-3 rounded-sm overflow-x-auto
                            max-h-72 leading-relaxed">
{JSON.stringify(handoff.data, null, 2)}
            </pre>
          </section>
        )}

        <div className="space-y-5">
          {Object.entries(fields).map(([section, values]) => (
            <section key={section} className="panel">
              <h2 className="label px-4 py-2.5 border-b hair">
                {titleise(section.replace(/^section_\d+_/, ''))}
              </h2>
              <dl className="divide-y divide-[#263037]">
                {Object.entries(values as Record<string, unknown>).map(([key, value]) => (
                  <div key={key} className="grid grid-cols-1 sm:grid-cols-[220px_1fr] gap-1 sm:gap-4 px-4 py-2.5">
                    <dt className="text-xs text-muted">{titleise(key)}</dt>
                    <dd className="text-xs">
                      <FieldValue value={value} />
                    </dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
        </div>
      </div>
    </div>
  )
}

function FieldValue({ value }: { value: unknown }) {
  if (value === NOT_AVAILABLE) {
    return <span className="font-mono text-coral tracking-wider">{NOT_AVAILABLE}</span>
  }
  if (value === null || value === undefined) {
    return <span className="font-mono text-coral tracking-wider">{NOT_AVAILABLE}</span>
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-dim">—</span>
    return (
      <ul className="space-y-1">
        {value.map((item, i) => (
          <li key={i} className="font-mono text-2xs text-ink">
            {typeof item === 'object' && item !== null
              ? Object.entries(item as Record<string, unknown>)
                  .map(([k, v]) => `${k}: ${String(v)}`)
                  .join('  ·  ')
              : String(item)}
          </li>
        ))}
      </ul>
    )
  }
  if (typeof value === 'object') {
    return (
      <span className="font-mono text-2xs text-ink">
        {Object.entries(value as Record<string, unknown>)
          .map(([k, v]) => `${k}: ${String(v)}`)
          .join('  ·  ')}
      </span>
    )
  }
  if (typeof value === 'boolean') {
    return <span className={`font-mono ${value ? 'text-sodium' : 'text-muted'}`}>{value ? 'YES' : 'NO'}</span>
  }
  return <span className="font-mono text-ink break-words">{String(value)}</span>
}
