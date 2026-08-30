import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api, followJob } from '@/lib/api'
import type { Job, RegionProperties } from '@/lib/types'
import { useOpsMap, upsertGeoJson, SLICK_LAYERS } from '@/components/map/OpsMap'
import { Stat } from '@/components/primitives/Panel'
import { Button } from '@/components/primitives/Button'
import { ModeBadge } from '@/components/primitives/Badge'
import { EmptyState, ErrorState, ProgressRail, Skeleton } from '@/components/primitives/States'
import { bboxCentre, compass, num, titleise, utcStamp } from '@/lib/format'

export function SceneView() {
  const { sceneId = '' } = useParams()
  const navigate = useNavigate()
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [openRegion, setOpenRegion] = useState<number | null>(0)

  const scene = useQuery({ queryKey: ['scene', sceneId], queryFn: () => api.scene(sceneId), enabled: !!sceneId })
  const detections = useQuery({
    queryKey: ['detections', sceneId],
    queryFn: () => api.detections(sceneId),
    enabled: !!sceneId,
  })

  const centre = bboxCentre(scene.data?.bbox)
  const { map, ready, setContainer } = useOpsMap({ center: centre, zoom: 8.2 })

  // Fit to the scene and lay the SAR raster underneath the vectors.
  useEffect(() => {
    if (!map || !ready || !scene.data?.bbox) return
    const [w, s, e, n] = scene.data.bbox
    map.fitBounds([[w, s], [e, n]], { padding: 40, duration: 600 })
    if (!map.getSource('sar')) {
      map.addSource('sar', {
        type: 'image',
        url: api.rasterUrl(sceneId),
        coordinates: [[w, n], [e, n], [e, s], [w, s]],
      })
      map.addLayer({
        id: 'sar-layer', type: 'raster', source: 'sar',
        paint: {
          'raster-opacity': 0.95,
          // Nearest-neighbour, not bilinear. Past the raster's native
          // resolution, smoothing invents detail that is not in the
          // measurement -- an analyst zooming into a slick edge should see the
          // real sigma0 pixels, not an interpolation of them.
          'raster-resampling': 'nearest',
          'raster-fade-duration': 0,
        },
      })
    }
  }, [map, ready, scene.data, sceneId])

  useEffect(() => {
    if (!map || !ready || !detections.data?.detections) return
    upsertGeoJson(map, 'regions', detections.data.detections, SLICK_LAYERS('regions'))
    const ships = detections.data.ship_contacts ?? []
    upsertGeoJson(
      map,
      'ships',
      {
        type: 'FeatureCollection',
        features: ships.map((p: { lon: number; lat: number }) => ({
          type: 'Feature' as const, properties: {},
          geometry: { type: 'Point' as const, coordinates: [p.lon, p.lat] },
        })),
      },
      [{
        id: 'ships-symbol', type: 'circle', source: 'ships',
        paint: { 'circle-radius': 3, 'circle-color': '#F3F5F0', 'circle-opacity': 0.85,
                 'circle-stroke-width': 1, 'circle-stroke-color': '#050709' },
      }],
    )
  }, [map, ready, detections.data])

  const findCandidates = useCallback(async () => {
    setError(null)
    try {
      const { job_id } = await api.generateCandidates({ scene_id: sceneId })
      await followJob(job_id, setJob)
      setJob(null)
      navigate(`/scene/${sceneId}?candidates=1`, { replace: true })
      const { job_id: runJob } = await api.runAttribution({ scene_id: sceneId })
      const finished = await followJob(runJob, setJob)
      setJob(null)
      const runId = finished.result?.run_id as string | undefined
      if (runId) navigate(`/attribution/${runId}`)
    } catch (cause) {
      setJob(null)
      setError(cause)
    }
  }, [sceneId, navigate])

  if (scene.isLoading) {
    return <div className="p-6 max-w-4xl"><Skeleton rows={6} /></div>
  }
  if (scene.isError) {
    return <div className="p-6 max-w-2xl"><ErrorState error={scene.error} onRetry={() => scene.refetch()} /></div>
  }

  const coverage = detections.data?.coverage ?? scene.data?.wind_gate?.coverage
  const gate = scene.data?.wind_gate
  const features = (detections.data?.detections?.features ?? []) as {
    id: number; properties: RegionProperties
  }[]
  const slicks = features.filter((f) => f.properties.class === 'oil')
  const lookalikes = features.filter((f) => f.properties.class !== 'oil')

  return (
    <div className="analysis-layout flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[1fr_400px] lg:grid-rows-[minmax(0,1fr)]">
      <div className="analysis-map relative min-h-[45vh] lg:min-h-0 scanlines order-1">
        <div ref={setContainer} role="group" className="h-full w-full" aria-label="Sentinel-1 scene with detected regions" />
        <div className="map-record-panel absolute top-3 left-3 panel px-3 py-2 pointer-events-none max-w-[280px]">
          <div className="flex items-center gap-2 mb-1">
            <span className="label">Sentinel-1 IW · σ⁰ VV</span>
            <ModeBadge mode={scene.data.mode} />
          </div>
          <div className="num text-2xs text-muted">{utcStamp(scene.data.acquired_utc)}</div>
        </div>
        <div className="map-record-panel absolute bottom-3 left-3 panel px-3 py-2 pointer-events-none">
          <div className="label mb-1">Legend</div>
          <div className="flex flex-col gap-1 text-2xs">
            <span className="flex items-center gap-2 text-radar">
              <span className="w-3 h-0.5 bg-radar" aria-hidden /> observed slick
            </span>
            <span className="flex items-center gap-2 text-muted">
              <span className="w-3 border-t border-dashed border-muted" aria-hidden /> look-alike
            </span>
            <span className="flex items-center gap-2 text-ink">
              <span className="w-1.5 h-1.5 rounded-full bg-ink" aria-hidden /> radar ship contact
            </span>
          </div>
        </div>
      </div>

      <aside className="analysis-console flex flex-col min-h-0 border-l hair bg-panel overflow-y-auto order-2">
        {/* The wind gate is always visible, whether it passed or not. */}
        {coverage && !coverage.sufficient && (
          <div className="p-4 border-b hair bg-sodium/5" data-testid="coverage-warning">
            <div className="flex items-center gap-2 mb-2">
              <span className="label">Swath coverage</span>
              <span className="text-2xs font-mono px-1.5 py-0.5 border text-sodium border-sodium/40 bg-sodium/10">
                PARTIAL
              </span>
            </div>
            <div className="grid grid-cols-2 gap-3 mb-3">
              <Stat label="Imaged" value={num(coverage.percent, 0)} unit="%" tone="sodium" />
              <Stat label="Required" value={num(coverage.min_fraction * 100, 0)} unit="%" tone="muted" />
            </div>
            <p className="text-xs text-muted leading-relaxed">{coverage.verdict}</p>
          </div>
        )}

        {gate && (
          <div className={`p-4 border-b hair ${gate.passed ? '' : 'bg-sodium/5'}`} data-testid="wind-gate">
            <div className="flex items-center gap-2 mb-2">
              <span className="label">Wind gate</span>
              <span className={`text-2xs font-mono px-1.5 py-0.5 border ${
                gate.passed ? 'text-sage border-sage/40 bg-sage/10' : 'text-sodium border-sodium/40 bg-sodium/10'
              }`}>
                {gate.passed ? 'PASSED' : 'GATED'}
              </span>
            </div>
            <div className="grid grid-cols-3 gap-3 mb-3">
              <Stat label="Speed" value={num(gate.wind_speed_ms, 1)} unit="m/s"
                    tone={gate.passed ? 'radar' : 'sodium'} />
              <Stat label="Direction" value={`${num(gate.wind_direction_deg, 0)}°`}
                    unit={compass(gate.wind_direction_deg)} tone="muted" />
              <Stat label="Band" value={`${num(gate.min_ms, 0)}–${num(gate.max_ms, 0)}`} unit="m/s" tone="muted" />
            </div>
            <p className="text-xs text-muted leading-relaxed">{gate.verdict}</p>
            <p className="text-2xs text-dim mt-2 font-mono">{gate.source}</p>
          </div>
        )}

        <div className="p-4 border-b hair">
          <div className="flex items-center justify-between mb-3">
            <span className="label">Detected regions</span>
            {detections.data?.mode && <ModeBadge mode={detections.data.mode} />}
          </div>
          {detections.isLoading && <Skeleton rows={3} />}
          {detections.isError && (
            <ErrorState error={detections.error} onRetry={() => detections.refetch()} />
          )}
          {detections.isSuccess && features.length === 0 && (
            <EmptyState
              icon="○"
              title="No dark regions in this scene"
              body={
                coverage && !coverage.sufficient
                  ? `Only ${Math.round(coverage.percent)}% of this box falls inside the acquisition's swath. Most of the area was never imaged, so finding nothing here says very little about it.`
                  : gate && !gate.passed
                    ? 'The scene is outside the wind band where oil produces radar contrast, so an absence of detections here carries no information.'
                    : 'The segmenter found no region meeting the minimum area and contrast thresholds. That is a valid result for a clean scene.'
              }
            />
          )}
          {features.length > 0 && (
            <div className="grid grid-cols-2 gap-3 mb-3">
              <Stat label="Slicks" value={slicks.length} tone="radar" />
              <Stat label="Look-alikes rejected" value={lookalikes.length} tone="muted" />
            </div>
          )}
        </div>

        {/* Every discriminating feature, with its value, threshold and weight.
            No black box. */}
        {features.length > 0 && (
          <div className="p-4 border-b hair space-y-2" data-testid="lookalike-panel">
            <div className="label mb-2">Why each region was classified</div>
            {features.map((feature, i) => {
              const props = feature.properties
              const open = openRegion === i
              return (
                <div key={feature.id} className="border hair bg-raised">
                  <button
                    onClick={() => setOpenRegion(open ? null : i)}
                    aria-expanded={open}
                    className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-panel/60 transition-colors"
                  >
                    <span className={`w-2 h-2 rounded-full shrink-0 ${
                      props.class === 'oil' ? 'bg-radar' : 'bg-muted'
                    }`} aria-hidden />
                    <span className="text-xs font-mono text-ink flex-1">
                      {props.class === 'oil' ? 'OIL' : 'LOOK-ALIKE'}
                    </span>
                    <span className="num text-2xs text-muted">{num(props.area_km2, 2)} km²</span>
                    <span className="num text-2xs text-dim">{num(props.confidence * 100, 0)}%</span>
                    <span aria-hidden className="text-dim text-xs">{open ? '−' : '+'}</span>
                  </button>
                  {open && (
                    <div className="px-3 pb-3 pt-1 border-t hair space-y-2">
                      <div className="grid grid-cols-2 gap-2 text-2xs mb-2">
                        <div><span className="text-dim">axis </span>
                          <span className="num text-muted">{num(props.major_axis_deg, 0)}° {compass(props.major_axis_deg)}</span></div>
                        <div><span className="text-dim">length </span>
                          <span className="num text-muted">{num(props.major_axis_length_km, 1)} km</span></div>
                      </div>
                      {props.reasons.map((reason) => (
                        <div key={reason.feature} className="text-2xs">
                          <div className="flex items-baseline gap-2">
                            <span className={`w-1 h-1 rounded-full shrink-0 ${
                              reason.supports === 'oil' ? 'bg-radar' : 'bg-muted'
                            }`} aria-hidden />
                            <span className="text-muted flex-1">{titleise(reason.feature)}</span>
                            <span className="num text-ink">
                              {reason.value === null ? 'n/a' : num(reason.value, 2)}
                            </span>
                            <span className="num text-dim">
                              {reason.comparison === 'ge' ? '≥' : '≤'} {num(reason.threshold, 2)}
                            </span>
                            <span className="num text-dim">×{num(reason.weight, 1)}</span>
                          </div>
                          <p className="text-dim ml-3 mt-0.5 leading-snug">{reason.note}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}

        <div className="p-4 mt-auto sticky bottom-0 bg-panel border-t hair space-y-3">
          {job && <ProgressRail stage={job.stage} progress={job.progress} log={job.log} />}
          {error != null && <ErrorState error={error} onRetry={() => setError(null)} />}
          <Button
            variant="primary"
            onClick={findCandidates}
            disabled={job !== null || slicks.length === 0 || !gate?.passed}
            className="w-full py-2.5"
            data-testid="find-candidates"
          >
            {job ? 'RUNNING…' : 'FIND CANDIDATE VESSELS'}
          </Button>
          {slicks.length === 0 && (
            <p className="text-2xs text-dim text-center">
              Attribution needs a segmented slick to compare simulations against.
            </p>
          )}
          {slicks.length > 0 && !gate?.passed && (
            <p className="text-2xs text-sodium text-center leading-snug">
              Attribution is disabled on a wind-gated scene: it would rest on a detection
              the physics does not support.
            </p>
          )}
        </div>
      </aside>
    </div>
  )
}
