import { useState } from 'react'
import { api, type Opportunity } from '../api'

type Props = {
  opportunities: Opportunity[]
  onExecuted: () => void
}

function ageSeconds(iso: string): number {
  return Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000))
}

export function OpportunityBoard({ opportunities, onExecuted }: Props) {
  const [busyId, setBusyId] = useState<string | null>(null)
  const [notional, setNotional] = useState(100)
  const [error, setError] = useState<string | null>(null)

  async function execute(opp: Opportunity) {
    setBusyId(opp.id)
    setError(null)
    try {
      await api.execute(opp.id, notional)
      onExecuted()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-panel)]/80 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="m-0 text-lg font-medium">Opportunities</h2>
          <p className="m-0 mt-1 text-xs text-[var(--muted)]">
            Theoretical · net edge after taker fees + slippage
          </p>
        </div>
        <label className="flex items-center gap-2 text-sm text-[var(--muted)]">
          Paper notional (USDT)
          <input
            type="number"
            min={1}
            step={10}
            value={notional}
            onChange={(e) => setNotional(Number(e.target.value))}
            className="w-24 rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1 text-[var(--text)]"
          />
        </label>
      </div>

      {error && (
        <p className="mb-3 rounded border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-3 py-2 text-sm text-[var(--danger)]">
          {error}
        </p>
      )}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] border-collapse text-left text-sm">
          <thead>
            <tr className="border-b border-[var(--border)] text-[var(--muted)]">
              <th className="py-2 font-medium">Pair</th>
              <th className="py-2 font-medium">Buy</th>
              <th className="py-2 font-medium">Sell</th>
              <th className="py-2 font-medium">Raw %</th>
              <th className="py-2 font-medium">Net %</th>
              <th className="py-2 font-medium">Fees</th>
              <th className="py-2 font-medium">Age</th>
              <th className="py-2 font-medium" />
            </tr>
          </thead>
          <tbody>
            {opportunities.length === 0 && (
              <tr>
                <td colSpan={8} className="py-8 text-center text-[var(--muted)]">
                  No net-positive edges right now — scanning…
                </td>
              </tr>
            )}
            {opportunities.map((o) => (
              <tr key={o.id} className="border-b border-[var(--border)]/60">
                <td className="py-2.5 font-medium">{o.symbol}</td>
                <td className="py-2.5">
                  <span className="text-[var(--buy)]">{o.buy_exchange}</span>
                  <span className="ml-2 text-[var(--muted)]">{o.buy_price.toFixed(2)}</span>
                </td>
                <td className="py-2.5">
                  <span className="text-[var(--sell)]">{o.sell_exchange}</span>
                  <span className="ml-2 text-[var(--muted)]">{o.sell_price.toFixed(2)}</span>
                </td>
                <td className="py-2.5">{o.raw_edge_pct.toFixed(3)}</td>
                <td className="py-2.5 font-semibold text-[var(--accent)]">
                  {o.net_edge_pct.toFixed(3)}
                </td>
                <td className="py-2.5 text-[var(--muted)]">
                  {(o.buy_fee_pct + o.sell_fee_pct).toFixed(2)}% + slip{' '}
                  {o.slippage_pct.toFixed(2)}%
                </td>
                <td className="py-2.5 text-[var(--muted)]">{ageSeconds(o.detected_at)}s</td>
                <td className="py-2.5 text-right">
                  <button
                    type="button"
                    disabled={busyId === o.id}
                    onClick={() => void execute(o)}
                    className="rounded bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-[#062016] disabled:opacity-50"
                  >
                    {busyId === o.id ? '…' : 'Paper exec'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
