import { useQuery } from '@tanstack/react-query'
import {
  Bar, CartesianGrid, Cell, Line, ComposedChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'
import { api } from '@/lib/api'
import { Panel, Stat } from '@/components/primitives/Panel'
import { EmptyState, ErrorState, Skeleton } from '@/components/primitives/States'
import { num } from '@/lib/format'

export function Calibration() {
  const calibration = useQuery({ queryKey: ['calibration'], queryFn: api.calibration, retry: 0 })

  if (calibration.isLoading) return <div className="p-6 max-w-4xl"><Skeleton rows={6} /></div>

  if (calibration.isError) {
    const notFound = (calibration.error as any)?.status === 404
    return (
      <div className="flex-1 flex items-center justify-center p-6">
        {notFound ? (
          <EmptyState
            icon="◔"
            title="No calibration computed on this deployment"
            body="The reliability curve is computed from real runs over a generated validation set, never hardcoded. Run scripts/make_synthetic_set.py to generate the set and fit the isotonic mapping."
          />
        ) : (
          <div className="max-w-2xl w-full">
            <ErrorState error={calibration.error} onRetry={() => calibration.refetch()} />
          </div>
        )}
      </div>
    )
  }

  const data = calibration.data
  const bins = (data.bins ?? []).filter((b: any) => b.count > 0).map((b: any) => ({
    bin: `${b.lo.toFixed(1)}–${b.hi.toFixed(1)}`,
    predicted: b.mean_predicted,
    observed: b.observed_frequency,
    count: b.count,
  }))

  return (
    <div className="record-page flex-1 overflow-y-auto">
      <div className="record-page__inner max-w-5xl mx-auto p-6">
        <header className="record-hero mb-6">
          <h1>Calibration</h1>
          <p className="text-xs text-muted max-w-3xl leading-relaxed">
            Accuracy and calibration are different properties, and only one of them tells an
            officer how much to trust a number. A system that ranks the true vessel first nine
            times in ten but reports 0.99 every time is accurate and badly calibrated — acting
            on it would mean treating a coin flip as a certainty. This page asks the other
            question: when AVANTA says 0.7, is it right about seven times in ten?
          </p>
        </header>

        <div className="metric-strip grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <Panel><Stat label="Brier score" value={num(data.brier_score, 4)} tone="radar"
                       hint="Mean squared error of the probability. Lower is better." /></Panel>
          <Panel><Stat label="Expected calibration error" value={num(data.expected_calibration_error, 4)}
                       tone="radar" hint="Average gap between stated probability and observed frequency." /></Panel>
          {/* This is the number of (predicted probability, outcome) pairs the
              metrics above are computed over, not a held-out split -- the
              isotonic mapping was fitted but not applied, so there is no split
              in force. Labelling it "held-out" would overstate the evidence. */}
          <Panel><Stat label="Scored predictions" value={data.n_cases} tone="ink" /></Panel>
          <Panel><Stat label="Bins with data" value={bins.length} tone="muted" /></Panel>
        </div>

        <Panel title="Reliability diagram" className="mb-6">
          {bins.length === 0 ? (
            <EmptyState icon="○" title="No populated bins"
                        body="The validation set produced no predictions in any bin." />
          ) : (
            <div className="h-80" data-testid="reliability-diagram">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={bins} margin={{ top: 10, right: 16, bottom: 28, left: 4 }}>
                  <CartesianGrid stroke="#263037" strokeDasharray="2 4" />
                  <XAxis dataKey="bin" stroke="#667277" tick={{ fontSize: 10, fontFamily: 'JetBrains Mono' }}
                         label={{ value: 'Predicted probability', position: 'insideBottom', offset: -16,
                                  fill: '#667277', fontSize: 11 }} />
                  <YAxis stroke="#667277" domain={[0, 1]} tick={{ fontSize: 10, fontFamily: 'JetBrains Mono' }}
                         label={{ value: 'Observed frequency', angle: -90, position: 'insideLeft',
                                  fill: '#667277', fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{ background: '#0A0E11', border: '1px solid #263037', fontSize: 11 }}
                    labelStyle={{ color: '#F3F5F0' }}
                  />
                  <Bar dataKey="observed" name="observed frequency" fill="#67F7D4">
                    {bins.map((_: unknown, i: number) => <Cell key={i} fill="#67F7D4" />)}
                  </Bar>
                  {/* Perfect calibration is the diagonal: bar height should equal predicted. */}
                  <Line type="monotone" dataKey="predicted" name="perfect calibration"
                        stroke="#FFB000" strokeWidth={1.5} strokeDasharray="4 3" dot={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}
        </Panel>

        <Panel title="Bin detail" className="mb-6">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left border-b hair">
                <th className="label py-2">Bin</th>
                <th className="label py-2 text-right">Count</th>
                <th className="label py-2 text-right">Mean predicted</th>
                <th className="label py-2 text-right">Observed</th>
                <th className="label py-2 text-right">Gap</th>
              </tr>
            </thead>
            <tbody>
              {bins.map((b: any) => (
                <tr key={b.bin} className="border-b hair">
                  <td className="num py-2 text-muted">{b.bin}</td>
                  <td className="num py-2 text-right text-muted">{b.count}</td>
                  <td className="num py-2 text-right text-ink">{num(b.predicted, 3)}</td>
                  <td className="num py-2 text-right text-radar">{num(b.observed, 3)}</td>
                  <td className={`num py-2 text-right ${
                    Math.abs(b.predicted - b.observed) > 0.15 ? 'text-coral' : 'text-muted'
                  }`}>
                    {num(Math.abs(b.predicted - b.observed), 3)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <section className="panel p-5 border-sodium/30">
          <h2 className="label text-sodium mb-2">What these numbers are computed on</h2>
          <p className="text-xs text-muted leading-relaxed">
            {data.notes || 'No note recorded for this calibration run.'}
          </p>
          <p className="text-xs text-muted leading-relaxed mt-3">
            These figures come from generated cases where the true source vessel is known exactly,
            with the slick simulated under one forcing realisation and attributed under a different
            one. They are not a validation against adjudicated real-world MARPOL cases — no corpus
            of those exists at a scale that would support one. Read them as a statement about the
            method's internal consistency, not about field performance.
          </p>
          <p className="text-2xs text-dim font-mono mt-3">
            computed {data.computed_at ?? '—'} ·{' '}
            {data.isotonic?.applied
              ? 'isotonic regression fitted on a held-out split and applied'
              : 'isotonic regression fitted on a held-out split, not applied — it did not improve ECE'}
          </p>
        </section>
      </div>
    </div>
  )
}
