import { useCallback, useEffect, useRef, useState } from 'react'
import maplibregl, { Map as MlMap } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'

/** Basemap.
 *  Deliberately not a street map. A dark bathymetric ground with a coastline
 *  and nothing else, so the only things carrying colour are the slick, the
 *  tracks and the particles. Raster tiles from a public source keep the app
 *  free of a tile-server dependency in an on-premise install; if it is offline,
 *  the ground goes flat dark and every data layer still renders. */
const STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    // Esri World Ocean Base: bathymetric contours and shaded relief, keyless.
    // It is the right ground for a maritime instrument -- the sea is the
    // subject here, not the road network -- and it carries the depth contours
    // the aesthetic calls for without a decorative overlay.
    ocean: {
      type: 'raster',
      tiles: ['https://services.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}'],
      tileSize: 256,
      minzoom: 0,
      // Esri's Ocean base stops at 13. Declaring it lets MapLibre upscale the
      // last real level instead of requesting tiles that do not exist.
      maxzoom: 13,
      attribution: 'Esri, GEBCO, NOAA, National Geographic, Garmin, HERE',
    },
    // Dark canvas over the top so land reads as absence rather than detail.
    dark: {
      type: 'raster',
      tiles: ['https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}'],
      tileSize: 256,
      minzoom: 0,
      maxzoom: 16,
      attribution: 'Esri',
    },
  },
  layers: [
    // If the network is unavailable the ground stays this colour and every
    // data layer still renders: the map degrades, the analysis does not.
    { id: 'ground', type: 'background', paint: { 'background-color': '#070C12' } },
    {
      // Bathymetry, pushed right down. It is texture and orientation, not
      // information the analyst reads values off, so it sits well below the
      // data layers in contrast.
      id: 'ocean', type: 'raster', source: 'ocean',
      paint: {
        'raster-opacity': 0.60,
        'raster-saturation': -0.60,
        'raster-brightness-max': 0.42,
        'raster-contrast': 0.18,
      },
    },
    {
      id: 'dark', type: 'raster', source: 'dark',
      paint: {
        'raster-opacity': 0.62,
        'raster-saturation': -0.45,
        'raster-brightness-max': 0.46,
      },
    },
    {
      // A cold tint over the ground so the whole chart sits in the abyssal
      // blue-black the rest of the interface is built on. Without it the
      // basemap reads warm and the cyan slick stops being the brightest thing
      // on screen -- which is the one thing it always has to be.
      id: 'tint', type: 'background',
      paint: { 'background-color': '#08111C', 'background-opacity': 0.34 },
    },
  ],
}

export interface MapHandle {
  map: MlMap | null
}

export function useOpsMap(options: { center: [number, number]; zoom: number }) {
  const mapRef = useRef<MlMap | null>(null)
  const observerRef = useRef<ResizeObserver | null>(null)
  const [ready, setReady] = useState(false)
  const [map, setMap] = useState<MlMap | null>(null)

  // A callback ref, not a plain ref with an empty-dependency effect.
  //
  // Every route that shows a map returns a loading skeleton first, so the map
  // container does not exist on the initial render. An effect with `[]`
  // dependencies runs once, finds `ref.current` still null, and never runs
  // again once the data arrives and the div finally mounts -- the map is then
  // silently absent, with no error anywhere to explain it. A callback ref fires
  // when the node actually attaches, which is the moment we need.
  const setContainer = useCallback(
    (node: HTMLDivElement | null) => {
      if (node === null) {
        observerRef.current?.disconnect()
        observerRef.current = null
        mapRef.current?.remove()
        mapRef.current = null
        setMap(null)
        setReady(false)
        return
      }
      if (mapRef.current) return

      const instance = new maplibregl.Map({
        container: node,
        style: STYLE,
        center: options.center,
        zoom: options.zoom,
        attributionControl: { compact: true },
        // Zoom bounds. Below 2 the Indian EEZ is smaller than the panel and
        // there is nothing to read; past 15 the basemap has no more detail at
        // sea and further zoom only magnifies interpolation. The SAR overlay
        // and every vector layer stay crisp across the whole range.
        minZoom: 1.5,
        maxZoom: 15,
        // The map is a chart, not a globe demo.
        pitchWithRotate: false,
        dragRotate: false,
      })
      instance.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right')
      instance.on('load', () => setReady(true))

      // The container is laid out by CSS grid, so its final height can arrive
      // after the map is constructed. Without this the canvas keeps whatever
      // size it was born with and the map renders into a sliver.
      const observer = new ResizeObserver(() => instance.resize())
      observer.observe(node)

      mapRef.current = instance
      observerRef.current = observer
      setMap(instance)
    },
    // The centre and zoom are only initial camera state; changing them later is
    // done with easeTo by the caller, not by rebuilding the map.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )

  useEffect(() => {
    return () => {
      observerRef.current?.disconnect()
      mapRef.current?.remove()
      mapRef.current = null
    }
  }, [])

  return { map, ready, setContainer }
}


export function upsertGeoJson(
  map: MlMap,
  id: string,
  data: GeoJSON.FeatureCollection | GeoJSON.Feature,
  layers: maplibregl.LayerSpecification[],
) {
  const existing = map.getSource(id) as maplibregl.GeoJSONSource | undefined
  if (existing) {
    existing.setData(data as never)
    return
  }
  map.addSource(id, { type: 'geojson', data: data as never })
  for (const layer of layers) {
    if (!map.getLayer(layer.id)) map.addLayer(layer)
  }
}

export function removeLayers(map: MlMap, sourceId: string, layerIds: string[]) {
  for (const id of layerIds) if (map.getLayer(id)) map.removeLayer(id)
  if (map.getSource(sourceId)) map.removeSource(sourceId)
}

/** Layer definitions, kept together so colour semantics stay consistent:
 *  cyan is always the observed slick, coral is always the attributed vessel,
 *  slate dashed is always a look-alike, amber is always a transmission gap. */
export const SLICK_LAYERS = (source: string): maplibregl.LayerSpecification[] => [
  {
    id: `${source}-glow`, type: 'line', source,
    filter: ['==', ['get', 'class'], 'oil'],
    paint: { 'line-color': '#3EC1D3', 'line-width': 9, 'line-opacity': 0.16, 'line-blur': 5 },
  },
  {
    id: `${source}-fill`, type: 'fill', source,
    filter: ['==', ['get', 'class'], 'oil'],
    paint: { 'fill-color': '#3EC1D3', 'fill-opacity': 0.20 },
  },
  {
    id: `${source}-line`, type: 'line', source,
    filter: ['==', ['get', 'class'], 'oil'],
    paint: { 'line-color': '#3EC1D3', 'line-width': 1.6 },
  },
  {
    id: `${source}-lookalike`, type: 'line', source,
    filter: ['!=', ['get', 'class'], 'oil'],
    paint: { 'line-color': '#8899AC', 'line-width': 1.2, 'line-dasharray': [3, 2], 'line-opacity': 0.8 },
  },
]

export const TRACK_LAYERS = (source: string): maplibregl.LayerSpecification[] => [
  {
    id: `${source}-line`, type: 'line', source,
    filter: ['==', ['get', 'segment'], 'transmitted'],
    paint: {
      'line-color': ['case', ['get', 'is_dark'], '#E5624F', '#F0A202'],
      'line-width': 1.8, 'line-opacity': 0.9,
    },
  },
  {
    // A gap is drawn dashed and amber because it is an absence of data, not a
    // path the vessel is known to have taken.
    id: `${source}-gap`, type: 'line', source,
    filter: ['==', ['get', 'segment'], 'gap'],
    paint: { 'line-color': '#E5624F', 'line-width': 2.2, 'line-dasharray': [1.5, 1.5], 'line-opacity': 0.95 },
  },
]

export const PARTICLE_LAYERS = (source: string): maplibregl.LayerSpecification[] => [
  {
    id: `${source}-halo`, type: 'circle', source,
    paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 6, 3.5, 11, 7],
      'circle-color': '#E5624F', 'circle-opacity': 0.10, 'circle-blur': 1.1,
    },
  },
  {
    id: `${source}-core`, type: 'circle', source,
    paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 6, 1.3, 11, 2.8],
      'circle-color': '#E5624F', 'circle-opacity': 0.68,
    },
  },
]
