import { useEffect, useRef } from 'react'
import type { AttributionResult } from '@/lib/types'
import { num, signed, titleise } from '@/lib/format'

/** The answer to "why this ship?", on one panel.
 *  Every term that produced the score, signed, with its raw value, adding up
 *  visibly to the number in the ranking. If these do not sum to the score, the
 *  panel is decoration rather than an audit trail — so the sum is shown. */
export function EvidenceDrawer({
  runId,
  mmsi,
  data,
  onClose,
}: {
  runId: string
  mmsi: string
  data: AttributionResult
  onClose: () => void
}) {
  const panelRef = useRef<HTMLDivElement>(null)
  const evidence = data.evidence?.[mmsi]
  const candidate = data.candidates?.find((c: any) => c.mmsi === mmsi)
  const entry = data.posterior.entries.find((e) => e.hypothesis_id === mmsi)

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    panelRef.current?.focus()
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  if (!evidence) {
    return null
  }

  const terms = [...evidence.terms].sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
  const maxAbs = Math.max(...terms.map((t) => Math.abs(t.value)), 1e-6)
  // What would most reduce confidence: the two terms pushing hardest against.
  const weakening = terms.filter((t) => t.value < 0).slice(0, 2)

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-abyss/70 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={`Evidence breakdown for ${entry?.label ?? mmsi}`}
      onClick={onClose}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-xl bg-panel border-l hair overflow-y-auto reveal"
        data-testid="evidence-drawer"
      >
        <header className="sticky top-0 bg-panel border-b hair px-5 py-3 flex items-center gap-3 z-10">
          <div className="flex-1 min-w-0">
            <h2 className="font-display text-base text-ink truncate">{entry?.label ?? mmsi}</h2>
            <p className="text-2xs text-dim font-mono">
              MMSI {mmsi} · run {runId}
            </p>
          </div>
          <button onClick={onClose} aria-label="Close evidence drawer"
                  className="text-muted hover:text-ink px-2 py-1 text-lg leading-none">×</button>
        </header>

        <div className="p-5 space-y-6">
          <div className="grid grid-cols-3 gap-4">
            <div>
              <div className="label mb-1">Posterior</div>
              <div className="num text-2xl text-coral leading-none">{num(entry?.probability ?? 0, 3)}</div>
            </div>
            <div>
              <div className="label mb-1">log likelihood</div>
              <div className="num text-lg text-ink leading-none">{num(evidence.log_likelihood, 2)}</div>
            </div>
            <div>
              <div className="label mb-1">log prior</div>
              <div className="num text-lg text-ink leading-none">{num(evidence.log_prior, 2)}</div>
            </div>
          </div>

          <section>
            <h3 className="label mb-3">Contributions to the log score</h3>
            <ul className="space-y-2.5">
              {terms.map((term) => {
                const width = (Math.abs(term.value) / maxAbs) * 50
                const positive = term.value >= 0
                return (
                  <li key={`${term.group}-${term.name}`} title={term.explanation}>
                    <div className="flex items-baseline gap-2 mb-1">
                      <span className={`text-2xs font-mono px-1 rounded-sm ${
                        term.group === 'likelihood'
                          ? 'text-radar bg-radar/10' : 'text-sodium bg-sodium/10'
                      }`}>
                        {term.group === 'likelihood' ? 'L' : 'π'}
                      </span>
                      <span className="text-xs text-muted flex-1 truncate">{titleise(term.name)}</span>
                      <span className={`num text-xs ${positive ? 'text-sage' : 'text-coral'}`}>
                        {signed(term.value, 3)}
                      </span>
                    </div>
                    {/* Diverging bar from a centre line: sign is visible at a glance. */}
                    <div className="relative h-1.5 bg-hairline rounded-sm" aria-hidden>
                      <div className="absolute left-1/2 top-0 bottom-0 w-px bg-dim" />
                      <div
                        className="absolute top-0 bottom-0 rounded-sm transition-all duration-500"
                        style={{
                          background: positive ? '#5FB58A' : '#E5624F',
                          width: `${width}%`,
                          left: positive ? '50%' : `${50 - width}%`,
                        }}
                      />
                    </div>
                    <p className="text-2xs text-dim mt-1 leading-snug">{term.explanation}</p>
                  </li>
                )
              })}
            </ul>
            <div className="flex items-baseline gap-2 mt-4 pt-3 border-t hair">
              <span className="text-xs text-muted flex-1">Sum of all terms</span>
              <span className="num text-sm text-ink">{num(evidence.sum, 4)}</span>
              <span className="text-2xs text-dim">= score</span>
              <span className="num text-sm text-ink">{num(evidence.score, 4)}</span>
            </div>
          </section>

          {weakening.length > 0 && (
            <section className="panel-raised p-4">
              <h3 className="label mb-2">What would change this</h3>
              <ul className="space-y-2">
                {weakening.map((term) => (
                  <li key={term.name} className="text-xs text-muted leading-relaxed">
                    <span className="text-coral font-mono">{titleise(term.name)}</span> is the
                    strongest term arguing against this attribution at{' '}
                    <span className="num text-ink">{signed(term.value, 3)}</span>. {term.explanation}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {candidate?.release && (
            <section>
              <h3 className="label mb-3">Maximum-likelihood release</h3>
              <dl className="grid grid-cols-2 gap-3 text-xs">
                {[
                  ['Start (UTC)', candidate.release.t_start],
                  ['End (UTC)', candidate.release.t_end],
                  ['Duration', `${num(candidate.release.duration_hours, 1)} h`],
                  ['Rate', `${num(candidate.release.rate_m3_per_h, 1)} m³/h`],
                  ['Volume', `${num(candidate.release.volume_m3, 1)} m³`],
                  ['Oil type', candidate.release.oil_type],
                ].map(([label, value]) => (
                  <div key={String(label)}>
                    <dt className="label mb-0.5">{label}</dt>
                    <dd className="num text-ink text-2xs break-words">{String(value)}</dd>
                  </div>
                ))}
              </dl>
            </section>
          )}

          {candidate?.seed && (
            <section>
              <h3 className="label mb-2">Seeding geometry</h3>
              <p className="text-xs text-muted leading-relaxed">
                Particles were seeded at{' '}
                <span className="num text-ink">{candidate.seed.distinct_seed_positions}</span> distinct
                positions along this vessel's own track, each at its own timestamp
                (<span className="num text-ink">{candidate.seed.distinct_seed_times}</span> distinct times),
                for a total of <span className="num text-ink">{candidate.seed.n_elements}</span> particles.
                This is a moving line source, not a point release — which is what produces the long,
                narrow slick geometry these events actually leave.
              </p>
            </section>
          )}
        </div>
      </div>
    </div>
  )
}
