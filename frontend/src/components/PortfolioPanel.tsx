import { useState } from 'react'
import { api, type Portfolio } from '../api'

type Props = {
  portfolio: Portfolio | null
  exchanges: string[]
  onChange: () => void
}

export function PortfolioPanel({ portfolio, exchanges, onChange }: Props) {
  const [asset, setAsset] = useState('USDT')
  const [fromVenue, setFromVenue] = useState(exchanges[0] ?? 'binance')
  const [toVenue, setToVenue] = useState(exchanges[1] ?? 'kraken')
  const [amount, setAmount] = useState(100)
  const [delayed, setDelayed] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function reset() {
    setBusy(true)
    setError(null)
    try {
      await api.resetPaper()
      onChange()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function transfer() {
    setBusy(true)
    setError(null)
    try {
      await api.transfer({
        asset,
        from_venue: fromVenue,
        to_venue: toVenue,
        amount,
        delayed,
      })
      onChange()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-panel)]/80 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="m-0 text-lg font-medium">Paper portfolio</h2>
          <p className="m-0 mt-1 text-xs text-[var(--muted)]">
            Realized PnL:{' '}
            <span className="text-[var(--accent)]">
              {(portfolio?.realized_pnl_usdt ?? 0).toFixed(4)} USDT
            </span>
          </p>
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={() => void reset()}
          className="rounded border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--muted)] hover:text-[var(--text)]"
        >
          Reset
        </button>
      </div>

      {error && (
        <p className="mb-3 rounded border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-3 py-2 text-sm text-[var(--danger)]">
          {error}
        </p>
      )}

      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        {Object.entries(portfolio?.by_venue ?? {}).map(([venue, assets]) => (
          <div key={venue} className="rounded border border-[var(--border)] bg-[var(--bg)]/60 p-3">
            <p className="m-0 text-xs uppercase tracking-wider text-[var(--muted)]">{venue}</p>
            <ul className="mt-2 space-y-1 text-sm">
              {Object.entries(assets).map(([a, amt]) => (
                <li key={a} className="flex justify-between gap-2">
                  <span className="text-[var(--muted)]">{a}</span>
                  <span>{amt < 1 ? amt.toFixed(6) : amt.toFixed(2)}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <div className="mb-4 rounded border border-[var(--border)]/80 p-3">
        <p className="m-0 mb-2 text-sm font-medium">Rebalance transfer</p>
        <div className="flex flex-wrap gap-2 text-sm">
          <select
            value={asset}
            onChange={(e) => setAsset(e.target.value)}
            className="rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1"
          >
            {['USDT', 'BTC', 'ETH', 'SOL'].map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
          <select
            value={fromVenue}
            onChange={(e) => setFromVenue(e.target.value)}
            className="rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1"
          >
            {exchanges.map((e) => (
              <option key={e} value={e}>
                {e}
              </option>
            ))}
          </select>
          <span className="self-center text-[var(--muted)]">→</span>
          <select
            value={toVenue}
            onChange={(e) => setToVenue(e.target.value)}
            className="rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1"
          >
            {exchanges.map((e) => (
              <option key={e} value={e}>
                {e}
              </option>
            ))}
          </select>
          <input
            type="number"
            min={0}
            step="any"
            value={amount}
            onChange={(e) => setAmount(Number(e.target.value))}
            className="w-28 rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1"
          />
          <label className="flex items-center gap-1.5 text-[var(--muted)]">
            <input
              type="checkbox"
              checked={delayed}
              onChange={(e) => setDelayed(e.target.checked)}
            />
            delayed flag
          </label>
          <button
            type="button"
            disabled={busy}
            onClick={() => void transfer()}
            className="rounded bg-[var(--sell)] px-3 py-1.5 font-medium text-[#0a1624] disabled:opacity-50"
          >
            Transfer
          </button>
        </div>
        <p className="mt-2 text-xs text-[var(--muted)]">
          Paper transfers are instant. The delayed flag only records that real withdrawals would
          take time.
        </p>
      </div>

      <div>
        <h3 className="m-0 mb-2 text-sm font-medium text-[var(--muted)]">Trade log</h3>
        <div className="max-h-48 overflow-auto text-sm">
          {(portfolio?.trades.length ?? 0) === 0 ? (
            <p className="text-[var(--muted)]">No paper trades yet.</p>
          ) : (
            <table className="w-full min-w-[560px] border-collapse">
              <thead>
                <tr className="text-left text-[var(--muted)]">
                  <th className="py-1 font-medium">Time</th>
                  <th className="py-1 font-medium">Route</th>
                  <th className="py-1 font-medium">Qty</th>
                  <th className="py-1 font-medium">PnL</th>
                </tr>
              </thead>
              <tbody>
                {portfolio!.trades.map((t) => (
                  <tr key={t.id} className="border-t border-[var(--border)]/50">
                    <td className="py-1.5 text-[var(--muted)]">
                      {new Date(t.executed_at).toLocaleTimeString()}
                    </td>
                    <td className="py-1.5">
                      {t.symbol} · {t.buy_exchange}→{t.sell_exchange}
                    </td>
                    <td className="py-1.5">{t.quantity.toFixed(6)}</td>
                    <td className="py-1.5 text-[var(--accent)]">{t.pnl_usdt.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </section>
  )
}
