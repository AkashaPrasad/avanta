import { useEffect } from 'react'
import { Activity, CircleHelp, ShieldCheck, X } from 'lucide-react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from './lib/api'
import { useUi } from './lib/store'
import { ModeBadge } from './components/primitives/Badge'

const SPINE = [
  { key: 'watch', label: 'Watch', match: (path: string) => path === '/' },
  { key: 'detect', label: 'Detect', match: (path: string) => path.startsWith('/scene') },
  { key: 'attribute', label: 'Attribute', match: (path: string) => path.startsWith('/attribution') },
  { key: 'evidence', label: 'Evidence', match: () => false },
  { key: 'dossier', label: 'Dossier', match: (path: string) => path.startsWith('/dossier') },
]

export function App() {
  const location = useLocation()
  const { shortcutsOpen, setShortcutsOpen } = useUi()
  const health = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    refetchInterval: 30_000,
    retry: 0,
  })

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return
      if (event.key === '?') {
        event.preventDefault()
        setShortcutsOpen(!shortcutsOpen)
      }
      if (event.key === 'Escape') setShortcutsOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [shortcutsOpen, setShortcutsOpen])

  const activeIndex = SPINE.findIndex((step) => step.match(location.pathname))

  return (
    <div className="app-shell min-h-screen flex flex-col bg-abyss">
      <a href="#main" className="skip-link">Skip to investigation console</a>

      <header className="command-header shrink-0">
        <div className="brand-lockup">
          <Link to="/" className="brand-name" aria-label="AVANTA home">
            <span className="brand-signal" aria-hidden />
            AVANTA
          </Link>
          <span className="brand-caption">MARITIME EVIDENCE RECORDER</span>
        </div>

        <nav aria-label="Investigation progress" className="investigation-spine">
          {SPINE.map((step, index) => {
            const state = index === activeIndex ? 'active' : index < activeIndex ? 'complete' : 'idle'
            return (
              <div key={step.key} className={`spine-step spine-step--${state}`} aria-current={state === 'active' ? 'step' : undefined}>
                <span className="spine-index">{String(index + 1).padStart(2, '0')}</span>
                <span>{step.label}</span>
                {index < SPINE.length - 1 && <span className="spine-line" aria-hidden />}
              </div>
            )
          })}
        </nav>

        <div className="header-tools">
          <nav aria-label="Reference views" className="reference-nav">
            <NavLink to="/calibration" className={({ isActive }) => isActive ? 'is-active' : ''}>
              Calibration
            </NavLink>
            <NavLink to="/about" className={({ isActive }) => isActive ? 'is-active' : ''}>
              Method
            </NavLink>
          </nav>
          <button className="icon-button" onClick={() => setShortcutsOpen(true)} aria-label="Keyboard shortcuts">
            <CircleHelp size={17} strokeWidth={1.7} />
          </button>
          <div className="system-state" title={health.isError ? 'The API is unreachable' : 'Backend status'}>
            {health.isError ? (
              <ModeBadge mode="DOWN" label="API DOWN" />
            ) : health.isLoading ? (
              <span className="status-loading"><Activity size={15} /> SYNC</span>
            ) : (
              <ModeBadge
                mode={health.data?.dependencies?.ais?.connected ? 'LIVE' : 'CACHED'}
                label={health.data?.dependencies?.ais?.connected ? 'AIS LIVE' : 'AIS STANDBY'}
              />
            )}
          </div>
        </div>
      </header>

      <main id="main" className="flex-1 min-h-0 flex flex-col">
        <Outlet />
      </main>

      {shortcutsOpen && <Shortcuts onClose={() => setShortcutsOpen(false)} />}
    </div>
  )
}

function Shortcuts({ onClose }: { onClose: () => void }) {
  const rows = [
    ['J / K', 'Move through the alert queue'],
    ['Enter', 'Open the selected scene'],
    ['R', 'Run the highlighted scenario'],
    ['A', 'Mark attributed'],
    ['D', 'Dismiss'],
    ['Space', 'Play or pause the particle record'],
    ['E', 'Open the evidence breakdown'],
    ['?', 'Open command reference'],
    ['Esc', 'Close the active surface'],
  ]

  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-label="Keyboard shortcuts" onClick={onClose}>
      <div className="shortcut-sheet" onClick={(event) => event.stopPropagation()}>
        <header className="shortcut-heading">
          <div>
            <ShieldCheck size={22} strokeWidth={1.5} />
            <h2>Command reference</h2>
          </div>
          <button onClick={onClose} className="icon-button" aria-label="Close keyboard shortcuts" autoFocus>
            <X size={18} />
          </button>
        </header>
        <dl className="shortcut-grid">
          {rows.map(([key, description]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>{description}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  )
}
