import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { AttributionResult, SimulationFrames } from '@/lib/types'
import {
  useOpsMap, upsertGeoJson, SLICK_LAYERS, TRACK_LAYERS, PARTICLE_LAYERS,
} from '@/components/map/OpsMap'
import { Button } from '@/components/primitives/Button'
import { ErrorState, Skeleton } from '@/components/primitives/States'
import { EvidenceDrawer } from '@/components/evidence/EvidenceDrawer'
import { num, utcStamp, viridis } from '@/lib/format'

type Overlay = 'observed' | 'simulated' | 'both' | 'difference'

export function Attribution() {
  const { runId = '' } = useParams()
  const [selected, setSelected] = useState<string | null>(null)
  const [overlay, setOverlay] = useState<Overlay>('both')
  const [frame, setFrame] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)

  const run = useQuery<AttributionResult>({
    queryKey: ['attribution', runId],
    queryFn: () => api.attribution(runId),
    enabled: !!runId,
  })

  const entries = run.data?.posterior.entries ?? []
  const named = entries.filter((e) => !e.is_null)
  const activeMmsi = selected ?? named[0]?.hypothesis_id ?? null

  const simulation = useQuery<SimulationFrames>({
    queryKey: ['sim', runId, activeMmsi],
    queryFn: () => api.simulation(runId, activeMmsi!),
    enabled: !!runId && !!activeMmsi,
  })

  const frames = useMemo(() => simulation.data?.frames ?? [], [simulation.data?.frames])
  const centre = useMemo<[number, number]>(() => {
    const slick = run.data?.slick?.features?.[0]
    if (slick?.geometry?.type === 'Polygon') {
      const ring = (slick.geometry as GeoJSON.Polygon).coordinates[0]
      const lon = ring.reduce((a, c) => a + c[0], 0) / ring.length
      const lat = ring.reduce((a, c) => a + c[1], 0) / ring.length
      return [lon, lat]
    }
    return [76.0, 12.0]
  }, [run.data])

  const { map, ready, setContainer } = useOpsMap({ center: centre, zoom: 8.6 })

  useEffect(() => {
    if (!map || !ready || !run.data) return
    map.easeTo({ center: centre, zoom: 8.6, duration: 600 })
  }, [map, ready, run.data, centre])

  // Observed slick
  useEffect(() => {
    if (!map || !ready || !run.data?.slick) return
    upsertGeoJson(map, 'obs', run.data.slick, SLICK_LAYERS('obs'))
    const visible = overlay === 'observed' || overlay === 'both' || overlay === 'difference'
    for (const id of ['obs-glow', 'obs-fill', 'obs-line', 'obs-lookalike']) {
      if (map.getLayer(id)) {
        map.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none')
      }
    }
  }, [map, ready, run.data, overlay])

  // Selected candidate's AIS track, with gaps dashed
  useEffect(() => {
    if (!map || !ready || !run.data || !activeMmsi) return
    const track = run.data.tracks?.[activeMmsi]
    if (track) upsertGeoJson(map, 'track', track, TRACK_LAYERS('track'))
  }, [map, ready, run.data, activeMmsi])

  // Particle cloud at the current frame
  useEffect(() => {
    if (!map || !ready) return
    const current = frames[Math.min(frame, frames.length - 1)]
    const show = overlay === 'simulated' || overlay === 'both' || overlay === 'difference'
    const features: GeoJSON.Feature[] =
      current && show
        ? current.lon.map((lon, i) => ({
            type: 'Feature' as const, properties: {},
            geometry: { type: 'Point' as const, coordinates: [lon, current.lat[i]] },
          }))
        : []
    upsertGeoJson(map, 'particles', { type: 'FeatureCollection', features }, PARTICLE_LAYERS('particles'))
  }, [map, ready, frames, frame, overlay])

  // Playback. Respects prefers-reduced-motion by jumping to the end state.
  useEffect(() => {
    if (!playing || frames.length === 0) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setFrame(frames.length - 1)
      setPlaying(false)
      return
    }
    const timer = window.setInterval(() => {
      setFrame((f) => {
        if (f >= frames.length - 1) { setPlaying(false); return f }
        return f + 1
      })
    }, 160)
    return () => window.clearInterval(timer)
  }, [playing, frames.length])

  useEffect(() => { setFrame(0); setPlaying(false) }, [activeMmsi])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target && ['INPUT', 'TEXTAREA', 'BUTTON'].includes(target.tagName)) return
      if (event.key === ' ') { event.preventDefault(); setPlaying((p) => !p) }
      if (event.key === 'e') setDrawerOpen((d) => !d)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const play = useCallback(() => {
    if (frame >= frames.length - 1) setFrame(0)
    setPlaying((p) => !p)
  }, [frame, frames.length])

  if (run.isLoading) return <div className="p-6 max-w-5xl"><Skeleton rows={8} /></div>
  if (run.isError) {
    return <div className="p-6 max-w-2xl"><ErrorState error={run.error} onRetry={() => run.refetch()} /></div>
  }

  const data = run.data!
  const noAttribution = data.posterior.no_attribution
  const top = named[0]
  const topSpread = top ? data.ensemble_spread?.[top.hypothesis_id] : undefined
  const currentFrame = frames[Math.min(frame, Math.max(0, frames.length - 1))]

  return (
    <div className="attribution-layout flex-1 min-h-0 flex flex-col">
      {/* The one-sentence answer, above the fold, in plain language. */}
      <div className={`verdict-strip shrink-0 px-4 py-3 border-b hair ${noAttribution ? 'is-null' : ''}`}>
        {noAttribution ? (
          <div data-testid="no-attribution">
            <div className="flex items-center gap-3 mb-1">
              <h1 className="font-display text-lg text-sodium tracking-wide">
                NO ATTRIBUTION — insufficient evidence
              </h1>
              <span className="num text-xs text-muted">p(unknown source) = {num(data.posterior.p_null, 3)}</span>
            </div>
            <p className="text-xs text-muted max-w-3xl leading-relaxed">
              No candidate vessel explains the observed slick better than the hypothesis that
              the source is something we are not looking at. Naming the top-ranked vessel here
              would be an accusation the evidence does not support. To resolve this you would
              need a wider AIS window, an earlier acquisition, or radar contacts that are
              currently outside the search box.
            </p>
          </div>
        ) : (
          <div>
            <h1 className="font-display text-lg text-ink mb-1" data-testid="attribution-headline">
              <span className="text-coral">{top?.label ?? '—'}</span> is the most probable source, at{' '}
              <span className="num text-coral">{num(top?.probability ?? 0, 2)}</span>
              {topSpread && topSpread.n > 1 && (
                <span className="num text-sm text-muted">
                  {' '}({num(Math.exp(-Math.abs(topSpread.width) / 40), 2)}–{num(top?.probability ?? 0, 2)} across {topSpread.n} ensemble members)
                </span>
              )}
            </h1>
            <p className="text-xs text-muted">
              Acquisition {utcStamp(data.acquisition_utc)} ·{' '}
              {named.length} candidate{named.length === 1 ? '' : 's'} simulated forward ·{' '}
              p(unknown source) = <span className="num">{num(data.posterior.p_null, 3)}</span>
            </p>
          </div>
        )}
      </div>

      <div className="attribution-grid flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[360px_1fr] lg:grid-rows-[minmax(0,1fr)]">
        {/* Ranked candidates. H0 is always a row, never hidden. */}
        <aside className="ranking-console flex flex-col min-h-0 border-r hair bg-panel overflow-y-auto order-2 lg:order-1">
          <div className="label px-4 py-2 border-b hair sticky top-0 bg-panel z-10">
            Ranked hypotheses · posterior sums to {num(data.posterior.sums_to, 4)}
          </div>
          <ul data-testid="candidate-ranking">
            {entries.map((entry, i) => (
              <li key={entry.hypothesis_id}>
                <button
                  onClick={() => !entry.is_null && setSelected(entry.hypothesis_id)}
                  disabled={entry.is_null}
                  data-testid={entry.is_null ? 'h0-row' : 'candidate-row'}
                  className={`reveal w-full text-left px-4 py-3 border-b hair transition-colors
                    ${entry.is_null ? 'bg-raised/40 cursor-default' : 'hover:bg-raised'}
                    ${activeMmsi === entry.hypothesis_id ? 'candidate-row--active' : ''}`}
                  style={{ animationDelay: `${Math.min(i, 8) * 50}ms` }}
                >
                  <div className="flex items-baseline gap-2 mb-1.5">
                    <span className="num text-2xs text-dim w-4">{entry.rank}</span>
                    <span className={`text-xs font-mono truncate flex-1 ${
                      entry.is_null ? 'text-sodium' : 'text-ink'
                    }`}>
                      {entry.label}
                    </span>
                    {entry.is_dark && (
                      <span className="text-2xs font-mono px-1 py-0.5 rounded-sm border
                                       border-coral/50 text-coral bg-coral/10">DARK</span>
                    )}
                    <span className="num text-sm text-ink">{num(entry.probability, 3)}</span>
                  </div>
                  <div className="h-1.5 bg-hairline overflow-hidden" aria-hidden>
                    <div
                      className="h-full transition-all duration-700"
                      style={{
                        width: `${Math.max(1.5, entry.probability * 100)}%`,
                        background: entry.is_null ? '#FFB000' : viridis(entry.probability),
                      }}
                    />
                  </div>
                  <div className="flex gap-3 mt-1.5 text-2xs text-dim">
                    <span className="num">logL {num(entry.log_likelihood, 1)}</span>
                    <span className="num">logπ {num(entry.log_prior, 2)}</span>
                    {!entry.is_null && entry.ship_type && <span>{entry.ship_type}</span>}
                  </div>
                </button>
              </li>
            ))}
          </ul>

          <div className="p-4 mt-auto border-t hair sticky bottom-0 bg-panel space-y-2">
            <Button variant="ghost" onClick={() => setDrawerOpen(true)} className="w-full"
                    data-testid="open-evidence">
              OPEN EVIDENCE BREAKDOWN
            </Button>
            {activeMmsi && !noAttribution && (
              <Link
                to={`/dossier/${runId}/${encodeURIComponent(activeMmsi)}`}
                className="block text-center px-3 py-2 text-xs font-mono tracking-[0.1em] uppercase
                           border border-radar/50 text-radar hover:bg-radar/15 transition-colors"
                data-testid="generate-dossier"
              >
                GENERATE DOSSIER
              </Link>
            )}
          </div>
        </aside>

        <div className="relative min-h-[48vh] lg:min-h-0 flex flex-col order-1 lg:order-2">
          <div className="relative flex-1 min-h-0 scanlines">
            <div ref={setContainer} role="group" className="h-full w-full"
                 aria-label="Observed slick, candidate track and simulated particles" />

            <div className="absolute top-3 left-3 flex gap-1 panel p-1" role="group" aria-label="Overlay">
              {(['observed', 'simulated', 'both', 'difference'] as Overlay[]).map((mode) => (
                <button
                  key={mode}
                  onClick={() => setOverlay(mode)}
                  aria-pressed={overlay === mode}
                  className={`px-2 py-1 text-2xs font-mono tracking-wider uppercase rounded-sm transition-colors ${
                    overlay === mode ? 'bg-radar/20 text-radar' : 'text-muted hover:text-ink'
                  }`}
                >
                  {mode}
                </button>
              ))}
            </div>

            {simulation.data?.seed?.degenerate && (
              <div className="absolute top-3 right-3 panel px-3 py-2 max-w-[300px] border-sodium/40">
                <div className="label text-sodium mb-1">Degenerate seeding</div>
                <p className="text-2xs text-muted leading-snug">
                  {simulation.data.seed.degenerate_reason}
                </p>
              </div>
            )}
          </div>

          {/* The centrepiece: particles seeding along the track over time. */}
          <div className="shrink-0 border-t hair bg-panel px-4 py-3" data-testid="timeline">
            <div className="flex items-center gap-3 mb-2">
              <Button variant="ghost" onClick={play} aria-label={playing ? 'Pause' : 'Play'}
                      disabled={frames.length === 0} className="w-16">
                {playing ? '❚❚ PAUSE' : '▶ PLAY'}
              </Button>
              <div className="flex-1 min-w-0">
                <input
                  type="range"
                  min={0}
                  max={Math.max(0, frames.length - 1)}
                  value={Math.min(frame, Math.max(0, frames.length - 1))}
                  onChange={(e) => { setPlaying(false); setFrame(Number(e.target.value)) }}
                  disabled={frames.length === 0}
                  aria-label="Simulation time"
                  className="w-full accent-[#FF5C35] h-1"
                />
              </div>
              <div className="num text-xs text-muted w-40 text-right shrink-0">
                {currentFrame ? utcStamp(currentFrame.t) : '—'}
              </div>
            </div>
            <div className="flex gap-5 text-2xs text-dim">
              <span className="num">
                particles <span className="text-muted">{currentFrame?.n ?? 0}</span>
              </span>
              <span className="num">
                surface oil <span className="text-muted">{num(currentFrame?.mass_kg ?? 0, 0)} kg</span>
              </span>
              {simulation.data?.seed && (
                <span className="num">
                  line source <span className="text-muted">
                    {simulation.data.seed.distinct_seed_positions} positions ·{' '}
                    {simulation.data.seed.distinct_seed_times} timestamps
                  </span>
                </span>
              )}
              {simulation.data?.oil && (
                <span className="num hidden md:inline">
                  oil <span className="text-muted">
                    {num(simulation.data.oil.density_kg_m3, 0)} kg/m³ ·{' '}
                    {num(simulation.data.oil.viscosity_cst, 0)} cSt
                  </span>
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      {drawerOpen && activeMmsi && (
        <EvidenceDrawer
          runId={runId}
          mmsi={activeMmsi}
          data={data}
          onClose={() => setDrawerOpen(false)}
        />
      )}
    </div>
  )
}
