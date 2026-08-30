import React, { lazy, Suspense } from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createBrowserRouter } from 'react-router-dom'
import '@fontsource/barlow-condensed/latin-400.css'
import '@fontsource/barlow-condensed/latin-500.css'
import '@fontsource/barlow-condensed/latin-600.css'
import '@fontsource/barlow-condensed/latin-700.css'
import '@fontsource/ibm-plex-sans/latin-400.css'
import '@fontsource/ibm-plex-sans/latin-500.css'
import '@fontsource/jetbrains-mono/latin-400.css'
import '@fontsource/jetbrains-mono/latin-600.css'
import './styles/tokens.css'
import { App } from './App'
import { Watch } from './routes/Watch'
import { Skeleton } from './components/primitives/States'

const SceneView = lazy(() => import('./routes/Scene').then((module) => ({ default: module.SceneView })))
const Attribution = lazy(() => import('./routes/Attribution').then((module) => ({ default: module.Attribution })))
const Dossier = lazy(() => import('./routes/Dossier').then((module) => ({ default: module.Dossier })))
const Calibration = lazy(() => import('./routes/Calibration').then((module) => ({ default: module.Calibration })))
const About = lazy(() => import('./routes/About').then((module) => ({ default: module.About })))
const NotFound = lazy(() => import('./routes/NotFound').then((module) => ({ default: module.NotFound })))

function DeferredRoute({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={<div className="p-6 max-w-4xl"><Skeleton rows={7} /></div>}>
      {children}
    </Suspense>
  )
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 15_000 },
  },
})

const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <Watch /> },
      { path: 'scene/:sceneId', element: <DeferredRoute><SceneView /></DeferredRoute> },
      { path: 'attribution/:runId', element: <DeferredRoute><Attribution /></DeferredRoute> },
      { path: 'dossier/:runId/:mmsi', element: <DeferredRoute><Dossier /></DeferredRoute> },
      { path: 'calibration', element: <DeferredRoute><Calibration /></DeferredRoute> },
      { path: 'about', element: <DeferredRoute><About /></DeferredRoute> },
      { path: '*', element: <DeferredRoute><NotFound /></DeferredRoute> },
    ],
  },
])

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </React.StrictMode>,
)
