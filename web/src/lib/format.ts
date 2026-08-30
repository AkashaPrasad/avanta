/** Viridis. Perceptually uniform and safe for every common form of colour
 *  vision deficiency, which red-to-green is not. Used for every magnitude. */
const VIRIDIS: [number, number, number][] = [
  [68, 1, 84], [72, 40, 120], [62, 74, 137], [49, 104, 142],
  [38, 130, 142], [31, 158, 137], [53, 183, 121], [109, 205, 89],
  [180, 222, 44], [253, 231, 37],
]

export function viridis(t: number): string {
  const x = Math.max(0, Math.min(1, Number.isFinite(t) ? t : 0)) * (VIRIDIS.length - 1)
  const i = Math.min(VIRIDIS.length - 2, Math.floor(x))
  const f = x - i
  const [r1, g1, b1] = VIRIDIS[i]
  const [r2, g2, b2] = VIRIDIS[i + 1]
  const mix = (a: number, b: number) => Math.round(a + (b - a) * f)
  return `rgb(${mix(r1, r2)}, ${mix(g1, g2)}, ${mix(b1, b2)})`
}

/** Never render a raw undefined or NaN into the interface. */
export function num(value: unknown, digits = 2, fallback = '—'): string {
  const n = typeof value === 'number' ? value : Number(value)
  if (value === null || value === undefined || !Number.isFinite(n)) return fallback
  return n.toFixed(digits)
}

export function pct(value: unknown, digits = 1): string {
  const n = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(n)) return '—'
  return `${(n * 100).toFixed(digits)}%`
}

export function signed(value: number, digits = 2): string {
  if (!Number.isFinite(value)) return '—'
  return `${value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(digits)}`
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (!Number.isFinite(then)) return '—'
  const seconds = Math.max(0, (Date.now() - then) / 1000)
  if (seconds < 90) return `${Math.round(seconds)}s ago`
  if (seconds < 5400) return `${Math.round(seconds / 60)}m ago`
  if (seconds < 172800) return `${Math.round(seconds / 3600)}h ago`
  return `${Math.round(seconds / 86400)}d ago`
}

export function utcStamp(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  return `${d.toISOString().slice(0, 16).replace('T', ' ')}Z`
}

export function titleise(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

/** Degrees to a compass point, for a heading a human has to read aloud. */
export function compass(deg: number): string {
  if (!Number.isFinite(deg)) return '—'
  const points = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                  'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
  return points[Math.round((((deg % 360) + 360) % 360) / 22.5) % 16]
}

export function bboxCentre(bbox: number[] | undefined): [number, number] {
  if (!bbox || bbox.length < 4) return [76.0, 12.0]
  return [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2]
}
