export type DataMode = 'LIVE' | 'CACHED' | 'FIXTURE' | 'SYNTHETIC' | 'DOWN'

export interface Scenario {
  id: string
  title: string
  subtitle: string
  kind: 'validation' | 'synthetic' | 'live' | string
  label: string
  honesty_note: string
  bbox: number[]
  known_source?: Record<string, unknown> | null
  t_from?: string | null
  t_to?: string | null
}

export interface Coverage {
  fraction: number
  percent: number
  min_fraction: number
  sufficient: boolean
  verdict: string
}

export interface WindGate {
  wind_speed_ms: number
  wind_direction_deg: number
  min_ms: number
  max_ms: number
  passed: boolean
  verdict: string
  source: string
  coverage?: Coverage
}

export interface Job {
  job_id: string
  kind: string
  status: 'queued' | 'running' | 'succeeded' | 'failed'
  stage: string
  progress: number
  result: Record<string, any> | null
  error: string | null
  log: string[]
}

export interface SceneSummary {
  id: string
  scenario: string | null
  bbox: number[]
  acquired_utc: string | null
  mode: DataMode
  status: string
  wind_gate: WindGate | null
  n_slicks: number
  created_at: string | null
}

export interface DetectionReason {
  feature: string
  value: number | null
  threshold: number
  weight: number
  comparison: string
  passed: boolean
  supports: 'oil' | 'look_alike'
  note: string
}

export interface RegionProperties {
  class: 'oil' | 'look_alike' | string
  confidence: number
  area_km2: number
  centroid: number[]
  major_axis_deg: number
  major_axis_length_km: number
  features: Record<string, number>
  reasons: DetectionReason[]
}

export interface PrefilterTerm {
  name: string
  value: number
  score: number
  explanation: string
}

export interface PrefilterResult {
  mmsi: string
  name: string | null
  ship_type: string
  is_dark: boolean
  total_score: number
  kept: boolean
  closest_approach_km: number
  terms: PrefilterTerm[]
}

export interface PosteriorEntry {
  hypothesis_id: string
  label: string
  probability: number
  log_likelihood: number
  log_prior: number
  score: number
  is_null: boolean
  rank: number
  is_dark?: boolean
  ship_type?: string
}

export interface EvidenceTerm {
  group: 'likelihood' | 'prior'
  name: string
  value: number
  explanation: string
}

export interface AttributionResult {
  run_id: string
  scene_id: string
  acquisition_utc: string
  posterior: {
    entries: PosteriorEntry[]
    p_null: number
    no_attribution: boolean
    h0_threshold: number
    sums_to: number
  }
  candidates: any[]
  null: Record<string, any>
  ensemble_spread: Record<string, { median: number; lo: number; hi: number; n: number; width: number }>
  evidence: Record<string, { terms: EvidenceTerm[]; sum: number; score: number; log_likelihood: number; log_prior: number }>
  tracks: Record<string, GeoJSON.FeatureCollection>
  slick: GeoJSON.FeatureCollection
  wind_gate: WindGate
  grid: { shape: number[]; downsample_factor: number; slick_cells: number }
  provenance: Record<string, any>
  runtime_s: number
}

export interface SimulationFrames {
  release: Record<string, any>
  seed: {
    n_elements: number
    n_vertices: number
    n_per_point: number
    distinct_seed_positions: number
    distinct_seed_times: number
    degenerate: boolean
    degenerate_reason: string | null
  }
  frames: { t: string; n: number; lon: number[]; lat: number[]; mass_kg: number }[]
  oil: { density_kg_m3: number; viscosity_cst: number }
}
