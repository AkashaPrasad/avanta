import { useCallback, useEffect, useMemo, useState } from 'react'
import { ArrowUpRight, Crosshair, RadioTower, ScanSearch, Waves } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, followJob, ApiError } from '@/lib/api'
import { useUi } from '@/lib/store'
import type { Job, Scenario, SceneSummary } from '@/lib/types'
import { useOpsMap, upsertGeoJson } from '@/components/map/OpsMap'
import { ModeBadge, StatusPill } from '@/components/primitives/Badge'
import { EmptyState, ErrorState, ProgressRail, Skeleton } from '@/components/primitives/States'
import { timeAgo, num } from '@/lib/format'

export function Watch() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { setLastSceneId } = useUi()
  const { map, ready, setContainer } = useOpsMap({ center: [76.5, 13.0], zoom: 4.6 })

  const [running, setRunning] = useState<{ scenario: string; job: Job } | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [selected, setSelected] = useState(0)

  const scenarios = useQuery({ queryKey: ['scenarios'], queryFn: api.scenarios })
  const scenes = useQuery({ queryKey: ['scenes'], queryFn: api.scenes, refetchInterval: 20_000 })
  const rows: SceneSummary[] = useMemo(() => scenes.data?.scenes ?? [], [scenes.data?.scenes])

  useEffect(() => {
    if (!map || !ready || rows.length === 0) return
    upsertGeoJson(
      map,
      'footprints',
      {
        type: 'FeatureCollection',
        features: rows.map((scene) => ({
          type: 'Feature' as const,
          properties: { id: scene.id, status: scene.status },
          geometry: {
            type: 'Polygon' as const,
            coordinates: [[
              [scene.bbox[0], scene.bbox[1]], [scene.bbox[2], scene.bbox[1]],
              [scene.bbox[2], scene.bbox[3]], [scene.bbox[0], scene.bbox[3]],
              [scene.bbox[0], scene.bbox[1]],
            ]],
          },
        })),
      },
      [
        {
          id: 'footprints-fill',
          type: 'fill',
          source: 'footprints',
          paint: { 'fill-color': '#67F7D4', 'fill-opacity': 0.08 },
        },
        {
          id: 'footprints-line',
          type: 'line',
          source: 'footprints',
          paint: { 'line-color': '#67F7D4', 'line-width': 1.5, 'line-opacity': 0.72 },
        },
      ],
    )
  }, [map, ready, rows])

  const runScenario = useCallback(
    async (scenario: Scenario) => {
      setError(null)
      try {
        const { job_id } = await api.ingest({ scenario: scenario.id })
        const finished = await followJob(job_id, (job) => setRunning({ scenario: scenario.id, job }))
        const sceneId = finished.result?.scene_id as string | undefined
        queryClient.invalidateQueries({ queryKey: ['scenes'] })
        setRunning(null)
        if (sceneId) {
          setLastSceneId(sceneId)
          navigate(`/scene/${sceneId}`)
        }
      } catch (cause) {
        setRunning(null)
        setError(cause)
      }
    },
    [navigate, queryClient, setLastSceneId],
  )

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target && ['INPUT', 'TEXTAREA'].includes(target.tagName)) return
      if (rows.length === 0) return
      if (event.key === 'j') setSelected((index) => Math.min(rows.length - 1, index + 1))
      if (event.key === 'k') setSelected((index) => Math.max(0, index - 1))
      if (event.key === 'Enter' && rows[selected]) navigate(`/scene/${rows[selected].id}`)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [rows, selected, navigate])

  const liveScenes = rows.filter((scene) => scene.mode === 'LIVE').length
  const gatedScenes = rows.filter((scene) => scene.status === 'GATED').length

  return (
    <div className="watch-layout flex-1 min-h-0">
      <aside className="watch-console">
        <section className="watch-thesis">
          <div className="thesis-icon" aria-hidden><Crosshair size={29} strokeWidth={1.25} /></div>
          <h1>Every vessel is a hypothesis.</h1>
          <p>
            Radar finds the slick. AVANTA runs each ship forward through the same ocean,
            then lets the evidence decide — including the decision to name nobody.
          </p>
          <div className="watch-readouts" aria-label="Watch status">
            <div><span>{String(rows.length).padStart(2, '0')}</span><small>records</small></div>
            <div><span>{String(liveScenes).padStart(2, '0')}</span><small>live</small></div>
            <div><span>{String(gatedScenes).padStart(2, '0')}</span><small>gated</small></div>
          </div>
        </section>

        <section className="scenario-deck" data-testid="scenario-list">
          <header>
            <h2>Run demo scenario</h2>
            <span>ONE CLICK · FULL CHAIN</span>
          </header>
          {scenarios.isLoading && <Skeleton rows={3} />}
          {scenarios.isError && <ErrorState error={scenarios.error} onRetry={() => scenarios.refetch()} />}
          <div className="scenario-list">
            {scenarios.data?.scenarios.map((scenario: Scenario, index: number) => (
              <button
                key={scenario.id}
                onClick={() => runScenario(scenario)}
                disabled={running !== null}
                data-testid={`run-scenario-${scenario.id}`}
                className="scenario-trigger reveal"
                style={{ animationDelay: `${index * 70}ms` }}
              >
                <span className="scenario-number">{String(index + 1).padStart(2, '0')}</span>
                <span className="scenario-copy">
                  <strong>{scenario.title}</strong>
                  <small>{scenario.subtitle}</small>
                  <span>{scenario.label}</span>
                </span>
                <span className="scenario-action">
                  <ModeBadge
                    mode={scenario.kind === 'synthetic' ? 'SYNTHETIC' : scenario.kind === 'live' ? 'LIVE' : 'CACHED'}
                    label={scenario.kind.toUpperCase()}
                  />
                  <ArrowUpRight size={18} strokeWidth={1.5} aria-hidden />
                </span>
              </button>
            ))}
          </div>
        </section>

        {running && (
          <div className="running-record">
            <ProgressRail stage={running.job.stage} progress={running.job.progress} log={running.job.log} />
          </div>
        )}
        {error != null && (
          <div className="running-record">
            <ErrorState
              title={error instanceof ApiError && error.status === 0 ? 'Backend unreachable' : 'Scenario failed'}
              error={error}
              onRetry={() => setError(null)}
            />
          </div>
        )}

        <section className="alert-ledger">
          <header>
            <h2>Acquisition ledger</h2>
            <span>{rows.length} RECORD{rows.length === 1 ? '' : 'S'}</span>
          </header>
          {scenes.isLoading && <div className="p-4"><Skeleton rows={4} /></div>}
          {scenes.isError && <div className="p-4"><ErrorState error={scenes.error} onRetry={() => scenes.refetch()} /></div>}
          {scenes.isSuccess && rows.length === 0 && (
            <EmptyState
              title="No acquisition records"
              body="Run a scenario to ingest Sentinel-1 data, test the wind gate, and start an evidence record."
            />
          )}
          <ul>
            {rows.map((scene, index) => (
              <li key={scene.id}>
                <button
                  onClick={() => navigate(`/scene/${scene.id}`)}
                  onFocus={() => setSelected(index)}
                  data-testid="alert-row"
                  // The J/K selection is a real state an analyst navigates by.
                  // Carrying it only in a CSS class hides it from assistive
                  // technology, so it is exposed here too.
                  aria-current={selected === index ? 'true' : undefined}
                  className={`ledger-row reveal ${selected === index ? 'is-selected' : ''}`}
                  style={{ animationDelay: `${Math.min(index, 8) * 45}ms` }}
                >
                  <span className="ledger-index">{String(index + 1).padStart(2, '0')}</span>
                  <span className="ledger-main">
                    <span className="ledger-badges"><StatusPill status={scene.status} /><ModeBadge mode={scene.mode} /></span>
                    <strong>{scene.scenario ?? scene.id}</strong>
                    <small>
                      {scene.n_slicks} slick{scene.n_slicks === 1 ? '' : 's'}
                      {scene.wind_gate && ` · wind ${num(scene.wind_gate.wind_speed_ms, 1)} m/s`}
                    </small>
                  </span>
                  <span className="ledger-time">{timeAgo(scene.created_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      </aside>

      <section className="watch-field scanlines" aria-label="Recent maritime acquisitions">
        {/* A schematic of the watch area, shown only until the basemap is up
            or if it never comes up at all -- an on-premise install may have no
            route to a tile server. It is a fallback, never an overlay: leaving
            it on top of a working map would mean showing an analyst a drawing
            of the ocean instead of the ocean. */}
        {!ready && <OfflineWatchChart rows={rows} />}
        <div ref={setContainer} role="group" className="h-full w-full" aria-label="Map of recent acquisitions" />
        <div className="field-sweep" aria-hidden />
        <div className="map-vignette" aria-hidden />
        <div className="map-identity">
          <span>INDIAN OCEAN / SENTINEL-1</span>
          <strong>Watch field</strong>
          <small>60–100°E · 0–25°N</small>
        </div>
        <div className="map-telemetry" aria-label="Map telemetry">
          <div><RadioTower size={15} /><span>Acquisition feed</span><strong>{ready ? 'LOCKED' : 'SYNCING'}</strong></div>
          <div><ScanSearch size={15} /><span>Footprints</span><strong>{rows.length}</strong></div>
          <div><Waves size={15} /><span>Drift model</span><strong>FORWARD</strong></div>
        </div>
        <div className="map-crosshair" aria-hidden><span /><span /></div>
        {running && (
          <div className="map-job-state" role="status" aria-live="polite">
            <span>RECORDING</span>
            <strong>{running.job.stage}</strong>
            <small>{Math.round(running.job.progress * 100)}% / {running.scenario}</small>
          </div>
        )}
      </section>
    </div>
  )
}

function OfflineWatchChart({ rows }: { rows: SceneSummary[] }) {
  const project = (lon: number, lat: number) => [
    ((lon - 60) / 40) * 1000,
    ((25 - lat) / 25) * 650,
  ] as const

  const visible = rows.flatMap((scene) => {
    const [west, south, east, north] = scene.bbox
    if (east < 60 || west > 100 || north < 0 || south > 25) return []
    const [x1, y1] = project(Math.max(60, west), Math.min(25, north))
    const [x2, y2] = project(Math.min(100, east), Math.max(0, south))
    return [{ id: scene.id, x: x1, y: y1, width: Math.max(8, x2 - x1), height: Math.max(8, y2 - y1) }]
  })

  return (
    <svg
      className="offline-watch-chart"
      viewBox="0 0 1000 650"
      preserveAspectRatio="xMidYMid slice"
      role="img"
      aria-label="Offline maritime chart fallback with acquisition geometry"
    >
      <defs>
        <pattern id="watch-grid" width="100" height="65" patternUnits="userSpaceOnUse">
          <path d="M 100 0 L 0 0 0 65" fill="none" />
        </pattern>
      </defs>
      <rect width="1000" height="650" className="chart-ground" />
      <rect width="1000" height="650" fill="url(#watch-grid)" className="chart-grid" />
      <g className="chart-contours" aria-hidden>
        <path d="M-30 520 C140 430 260 435 390 495 S680 610 1040 470" />
        <path d="M-20 570 C180 480 325 495 455 550 S765 655 1030 520" />
        <path d="M210 160 C330 120 445 145 520 245 S630 420 760 430" />
      </g>
      <g className="chart-coast" aria-hidden>
        <path d="M0 0 H265 L300 60 285 126 325 176 352 255 397 315 445 365 477 443 517 498 548 461 570 384 612 301 648 226 667 150 648 75 670 0 Z" />
        <path d="M528 515 L548 548 539 593 517 564 Z" />
        <path d="M850 0 L861 88 826 165 870 227 945 268 1000 275 V0 Z" />
      </g>
      <rect x="200" y="26" width="550" height="470" className="search-window" />
      <text x="214" y="49" className="chart-label">AIS WATCH BOUNDARY / 68–90°E</text>
      <g className="fallback-footprints">
        {visible.map((footprint) => (
          <g key={footprint.id}>
            <rect x={footprint.x} y={footprint.y} width={footprint.width} height={footprint.height} />
            <circle cx={footprint.x} cy={footprint.y} r="4" />
          </g>
        ))}
      </g>
    </svg>
  )
}
