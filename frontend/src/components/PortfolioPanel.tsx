import { useEffect, useMemo, useState } from 'react'
import { api, type EquityPoint, type Portfolio } from '../api'
import { HoverLineChart, type ChartDatum } from './HoverLineChart'

type Props = {
  portfolio: Portfolio | null
  exchanges: string[]
  onChange: () => void
  refreshKey?: number
}

export function PortfolioPanel({ portfolio, exchanges, onChange, refreshKey = 0 }: Props) {
  const [asset, setAsset] = useState('USDT')
  const [fromVenue, setFromVenue] = useState(exchanges[0] ?? 'binance')
  const [toVenue, setToVenue] = useState(exchanges[1] ?? 'kraken')
  const [amount, setAmount] = useState(100)
  const [delayed, setDelayed] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [equityNow, setEquityNow] = useState<number | null>(null)
  const [equityHist, setEquityHist] = useState<EquityPoint[]>([])
  const [rebalanceNote, setRebalanceNote] = useState<string | null>(null)

  useEffect(() => {
    void api
      .getEquity(400)
      .then((r) => {
        setEquityNow(r.current.equity_usdt)
        setEquityHist(r.history)
        const last = r.auto_rebalance?.last_result
        if (last?.ok && last.from_venue && last.to_venue) {
          setRebalanceNote(
            `Last auto transfer: ${Number(last.amount).toFixed(4)} ${last.asset} ${last.from_venue}→${last.to_venue}`,
          )
        } else if (last?.reason) {
          setRebalanceNote(last.reason)
        } else if (r.auto_rebalance?.enabled) {
          setRebalanceNote('Auto-rebalance ON — moves USDT/coins when a venue is short for an edge')
        } else {
          setRebalanceNote(null)
        }
      })
      .catch(() => {
        /* ignore */
      })
  }, [refreshKey, portfolio?.realized_pnl_usdt, portfolio?.trades.length])

  const chartMeta = useMemo(() => {
    if (equityHist.length < 2) return null
    const vals = equityHist.map((p) => p.equity_usdt)
    return {
      min: Math.min(...vals),
      max: Math.max(...vals),
      start: vals[0],
      end: vals[vals.length - 1],
    }
  }, [equityHist])

  const equityData: ChartDatum[] = useMemo(
    () =>
      equityHist.map((p) => ({
        y: p.equity_usdt,
        label: `${new Date(p.recorded_at).toLocaleString()}${p.note ? ` · ${p.note}` : ''}`,
        valueLabel: `${p.equity_usdt.toFixed(2)} USDT`,
      })),
    [equityHist],
  )

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

  const equityDelta =
    chartMeta == null ? null : chartMeta.end - chartMeta.start

  return (
    <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-panel)]/80 p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="m-0 text-lg font-medium">Paper portfolio</h2>
          <p className="m-0 mt-1 text-xs text-[var(--muted)]">
            Marked equity:{' '}
            <span className="text-[var(--accent)]">
              {(equityNow ?? 0).toFixed(2)} USDT
            </span>
            {' · '}
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

      <div className="mb-4 rounded border border-[var(--border)]/80 bg-[var(--bg)]/40 p-3">
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="m-0 text-sm font-medium">Equity over time</h3>
          <p className="m-0 text-xs text-[var(--muted)]">
            {chartMeta
              ? `${chartMeta.min.toFixed(0)} → ${chartMeta.max.toFixed(0)} · Δ ${equityDelta! >= 0 ? '+' : ''}${equityDelta!.toFixed(2)}`
              : 'Building history…'}
          </p>
        </div>
        {equityData.length >= 2 ? (
          <HoverLineChart
            data={equityData}
            ariaLabel="Paper equity over time"
            className="rounded border border-[var(--border)]/40 bg-[var(--bg)]/30"
          />
        ) : (
          <p className="m-0 text-sm text-[var(--muted)]">
            Equity curve starts after the first fills / rebalances (or a short heartbeat).
          </p>
        )}
        {rebalanceNote && (
          <p className="mt-2 m-0 text-xs text-[var(--muted)]">{rebalanceNote}</p>
        )}
      </div>

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
        <p className="m-0 mb-2 text-sm font-medium">Manual rebalance transfer</p>
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
          Auto-rebalance runs when an edge is blocked by inventory. Manual transfer is still
          available; paper moves are instant (delayed is a flag only).
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <h3 className="m-0 mb-2 text-sm font-medium text-[var(--muted)]">Trade log</h3>
          <div className="max-h-48 overflow-auto text-sm">
            {(portfolio?.trades.length ?? 0) === 0 ? (
              <p className="text-[var(--muted)]">No paper trades yet.</p>
            ) : (
              <table className="w-full min-w-[420px] border-collapse">
                <thead>
                  <tr className="text-left text-[var(--muted)]">
                    <th className="py-1 font-medium">Time</th>
                    <th className="py-1 font-medium">Route</th>
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
                      <td className="py-1.5 text-[var(--accent)]">{t.pnl_usdt.toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
        <div>
          <h3 className="m-0 mb-2 text-sm font-medium text-[var(--muted)]">Transfer log</h3>
          <div className="max-h-48 overflow-auto text-sm">
            {(portfolio?.transfers.length ?? 0) === 0 ? (
              <p className="text-[var(--muted)]">No transfers yet.</p>
            ) : (
              <table className="w-full min-w-[420px] border-collapse">
                <thead>
                  <tr className="text-left text-[var(--muted)]">
                    <th className="py-1 font-medium">Time</th>
                    <th className="py-1 font-medium">Move</th>
                    <th className="py-1 font-medium">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {portfolio!.transfers.map((t) => (
                    <tr key={t.id} className="border-t border-[var(--border)]/50">
                      <td className="py-1.5 text-[var(--muted)]">
                        {new Date(t.transferred_at).toLocaleTimeString()}
                      </td>
                      <td className="py-1.5">
                        {t.asset} · {t.from_venue}→{t.to_venue}
                        {t.delayed ? ' · auto/delayed' : ''}
                      </td>
                      <td className="py-1.5">{Number(t.amount).toFixed(6)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}
