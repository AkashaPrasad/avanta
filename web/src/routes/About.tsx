import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Panel } from '@/components/primitives/Panel'
import { Skeleton } from '@/components/primitives/States'

export function About() {
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, retry: 0 })

  return (
    <div className="record-page flex-1 overflow-y-auto">
      <div className="record-page__inner max-w-4xl mx-auto p-6">
        <header className="record-hero mb-10">
        <h1>Method</h1>
        <p className="text-sm text-muted max-w-2xl leading-relaxed">
          AVANTA turns a radar image of an oil slick into a ranked, calibrated, evidence-backed
          attribution — with an explicit option to name nobody.
        </p>
        </header>

        <section className="mb-10">
          <h2 className="font-display text-base text-radar mb-3">We run the drift forwards</h2>
          <div className="space-y-3 text-sm text-muted leading-relaxed max-w-2xl">
            <p>
              The obvious way to find the source of a slick is to run the drift backwards: take
              the oil you can see, integrate the currents in reverse, and look for ships in the
              box where it started. Existing bidirectional-drift methods do a version of this.
              It does not work, for two independent reasons.
            </p>
            <p>
              The first is that turbulent diffusion is a random walk, and a random walk has no
              inverse. Running the stochastic term backwards does not retrace the particles'
              path — it disperses them again. The "origin box" a backward run produces is an
              artefact of the diffusivity you chose, not a place. Breivik and colleagues showed
              this breakdown for reverse drift with stochastic terms.
            </p>
            <p>
              The second is that the slick you are reversing is not the slick that was released.
              Oil evaporates, emulsifies and disperses continuously, so its mass, area and drift
              properties at observation time are not the ones it had at release. Reversing the
              observed slick reverses the wrong object.
            </p>
            <p className="text-ink">
              So AVANTA inverts the workflow instead. For every ship that was in the area, it
              simulates forward the slick that ship <em>would have</em> left along its own AIS
              track, and compares each simulation to the real one. That is a hypothesis test per
              vessel, not an inverse problem — and forward integration of a stochastic process is
              well-posed. There is no backward time integration anywhere in the codebase, and a
              guard in the simulation runner refuses one.
            </p>
          </div>

          <div className="mt-6 panel p-5">
            <svg viewBox="0 0 640 190" className="w-full h-auto" role="img"
                 aria-label="Reverse drift diverges from a slick into an unusable origin box; forward simulation from each vessel track produces comparable slicks.">
              <defs>
                <marker id="arrowCoral" markerWidth="7" markerHeight="7" refX="6" refY="2.5" orient="auto">
                  <path d="M0,0 L6,2.5 L0,5 Z" fill="#E5624F" />
                </marker>
                <marker id="arrowSage" markerWidth="7" markerHeight="7" refX="6" refY="2.5" orient="auto">
                  <path d="M0,0 L6,2.5 L0,5 Z" fill="#5FB58A" />
                </marker>
              </defs>

              <text x="12" y="18" fill="#FF5C35" fontSize="11" fontFamily="JetBrains Mono">REVERSE — ill-posed</text>
              <ellipse cx="250" cy="52" rx="34" ry="12" fill="#67F7D4" fillOpacity="0.28" />
              <text x="292" y="56" fill="#A9B2B4" fontSize="10" fontFamily="JetBrains Mono">observed slick</text>
              {[[-26, -14], [-30, 0], [-26, 14], [-18, -22], [-18, 22]].map(([dx, dy], i) => (
                <line key={i} x1="216" y1="52" x2={150 + dx} y2={52 + dy * 1.7}
                      stroke="#FF5C35" strokeWidth="1.1" strokeOpacity="0.55"
                      strokeDasharray="3 2" markerEnd="url(#arrowCoral)" />
              ))}
              <rect x="70" y="20" width="62" height="66" fill="none" stroke="#FF5C35"
                    strokeOpacity="0.5" strokeDasharray="3 3" />
              <text x="52" y="102" fill="#FF5C35" fontSize="9" fontFamily="JetBrains Mono">
                origin box widens with diffusivity
              </text>

              <line x1="12" y1="118" x2="628" y2="118" stroke="#263037" />

              <text x="12" y="140" fill="#91D89E" fontSize="11" fontFamily="JetBrains Mono">FORWARD — well-posed</text>
              {[0, 1, 2].map((i) => (
                <g key={i}>
                  <line x1="70" y1={158 + i * 10} x2="150" y2={158 + i * 10}
                        stroke="#FFB000" strokeWidth="1.4" strokeOpacity="0.8" />
                  <line x1="150" y1={158 + i * 10} x2="228" y2={160 + i * 4}
                        stroke="#91D89E" strokeWidth="1.1" markerEnd="url(#arrowSage)" />
                </g>
              ))}
              <text x="66" y="152" fill="#FFB000" fontSize="9" fontFamily="JetBrains Mono">AIS tracks</text>
              <ellipse cx="252" cy="166" rx="26" ry="10" fill="#91D89E" fillOpacity="0.22" />
              <text x="288" y="170" fill="#A9B2B4" fontSize="10" fontFamily="JetBrains Mono">
                each simulated slick compared to the observation
              </text>
            </svg>
          </div>
        </section>

        <section className="mb-10">
          <h2 className="font-display text-base text-radar mb-3">A discharge is a line, not a point</h2>
          <p className="text-sm text-muted leading-relaxed max-w-2xl">
            A vessel discharging while under way lays oil down along its own track at its own
            speed. That is why these events leave long narrow slicks, and reproducing that
            geometry is what lets the test tell one vessel from another — a point release
            produces a roughly circular cloud that fits almost any candidate equally well. So
            particles are seeded at every vertex of the vessel's resampled track inside the
            release window, each at that vertex's own timestamp. A point-source fallback would
            be a bug, not a simplification.
          </p>
        </section>

        <section className="mb-10">
          <h2 className="font-display text-base text-radar mb-3">It can decline to accuse anyone</h2>
          <p className="text-sm text-muted leading-relaxed max-w-2xl">
            The posterior includes an explicit "unknown source" hypothesis, H0, scored against a
            diffuse null model. Without it, a softmax over candidates is normalised over a set
            that is <em>assumed</em> to contain the culprit, so the top-ranked vessel gets a high
            probability even when nothing fits. That is the failure mode that makes an automated
            enforcement tool dangerous: it cannot say "I don't know", so it accuses whoever was
            nearest. When p(H0) exceeds 0.5, this console refuses to rank vessels above it.
          </p>
        </section>

        <section className="mb-10">
          <h2 className="font-display text-base text-radar mb-3">Where it plugs in</h2>
          <p className="text-sm text-muted leading-relaxed max-w-2xl">
            INCOIS already runs an operational oil spill trajectory system — OOSA v4.0, built on
            NOAA GNOME, operational since 2014 over 60–100°E and 0–25°N, with Coast Guard
            officers trained on it. It answers "where will this oil go". It cannot start without
            a release point and time, and in a routine discharge nobody has one. AVANTA produces
            exactly that, plus the vessel. The <span className="font-mono text-ink">/handoff/oosa</span>{' '}
            endpoint emits the release specification in the shape GNOME needs. It is a handoff
            format, not a live connection.
          </p>
        </section>

        <Panel title="Runtime capability" mode={health.isError ? 'DOWN' : 'LIVE'}>
          {health.isLoading && <Skeleton rows={3} />}
          {health.isError && (
            <p className="text-xs text-coral font-mono">
              The API is unreachable, so the live capability state cannot be shown.
            </p>
          )}
          {health.data && (
            <dl className="space-y-2 text-xs">
              {Object.entries(health.data.dependencies ?? {}).map(([name, value]) => (
                <div key={name} className="flex items-start gap-3 py-1.5 border-b hair last:border-0">
                  <dt className="label w-24 shrink-0 pt-0.5">{name}</dt>
                  <dd className="font-mono text-2xs text-muted flex-1 break-words">
                    {Object.entries(value as Record<string, unknown>)
                      .map(([k, v]) => `${k}: ${JSON.stringify(v)}`)
                      .join('  ·  ')}
                  </dd>
                </div>
              ))}
            </dl>
          )}
          {health.data && (
            /* Outside the <dl>: a definition list may only contain dt/dd
               groups, and a div of loose spans inside one is invalid markup
               that assistive technology reads as a broken list. */
            <div className="flex gap-3 pt-2 mt-2 text-2xs text-dim font-mono">
              <span>config {String(health.data.config_sha).slice(0, 12)}</span>
              <span>code {String(health.data.git_sha).slice(0, 12)}</span>
            </div>
          )}
        </Panel>

        <p className="text-2xs text-dim mt-8 leading-relaxed">
          Sentinel-1 imagery: Copernicus Data Space Ecosystem. Wind: ECMWF ERA5 reanalysis.
          Currents and waves: Copernicus Marine Service, with a global ocean model fallback.
          Oil weathering: NOAA ADIOS via OpenDrift OpenOil. AIS: aisstream.io and Global Fishing
          Watch v3. Basemap © OpenStreetMap contributors © CARTO.
        </p>
      </div>
    </div>
  )
}
