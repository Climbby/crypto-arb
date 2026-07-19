import { useEffect, useMemo, useState } from 'react'
import { api, type HistoryRow, type Stats, type Tick } from '../api'

type Props = {
  prices: Tick[]
  refreshKey: number
  lastUpdateAt: number | null
  feedModes?: Record<string, string>
}

function formatPrice(symbol: string, value: number): string {
  if (symbol.includes('SOL') && symbol.includes('USDT')) return value.toFixed(4)
  if (symbol.includes('ETH') && symbol.includes('USDT')) return value.toFixed(3)
  if (symbol.includes('/BTC') || symbol.includes('/ETH')) return value.toFixed(6)
  return value.toFixed(2)
}

export function PricesAndHistory({ prices, refreshKey, lastUpdateAt, feedModes }: Props) {
  const [history, setHistory] = useState<HistoryRow[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [now, setNow] = useState(Date.now())
  const [hours, setHours] = useState(24)

  useEffect(() => {
    void api.getHistory(60).then((r) => setHistory(r.history))
    void api.getStats(hours).then(setStats).catch(() => setStats(null))
  }, [refreshKey, hours])

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [])

  const ageSec =
    lastUpdateAt == null ? null : Math.max(0, Math.floor((now - lastUpdateAt) / 1000))

  const chart = useMemo(() => {
    const buckets = stats?.buckets ?? []
    if (buckets.length === 0) return null
    const max = Math.max(...buckets.map((b) => Number(b.count) || 0), 1)
    const w = 560
    const h = 120
    const pad = 8
    const step = (w - pad * 2) / Math.max(buckets.length - 1, 1)
    const points = buckets.map((b, i) => {
      const x = pad + i * step
      const y = h - pad - ((Number(b.count) || 0) / max) * (h - pad * 2)
      return `${x},${y}`
    })
    return { w, h, points: points.join(' '), max }
  }, [stats])

  const majors = prices.filter(
    (p) => p.symbol === 'BTC/USDT' || p.symbol === 'ETH/USDT' || p.symbol === 'SOL/USDT',
  )

  return (
    <section className="grid gap-4 lg:grid-cols-2">
      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-panel)]/80 p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="m-0 text-lg font-medium">Live prices</h2>
          <p className="m-0 text-xs text-[var(--muted)]">
            {ageSec == null
              ? 'waiting…'
              : ageSec === 0
                ? 'updated just now'
                : `updated ${ageSec}s ago`}
            {feedModes && Object.keys(feedModes).length > 0 && (
              <span className="ml-2">
                · feeds{' '}
                {Object.entries(feedModes)
                  .map(([k, v]) => `${k}:${v}`)
                  .join(' ')}
              </span>
            )}
          </p>
        </div>
        <div className="mt-3 max-h-64 overflow-auto text-sm">
          {majors.length === 0 ? (
            <p className="text-[var(--muted)]">Waiting for first tick…</p>
          ) : (
            <table className="w-full border-collapse">
              <thead>
                <tr className="text-left text-[var(--muted)]">
                  <th className="py-1 font-medium">Venue</th>
                  <th className="py-1 font-medium">Pair</th>
                  <th className="py-1 font-medium">Bid</th>
                  <th className="py-1 font-medium">Ask</th>
                </tr>
              </thead>
              <tbody>
                {majors
                  .slice()
                  .sort(
                    (a, b) =>
                      a.symbol.localeCompare(b.symbol) || a.exchange.localeCompare(b.exchange),
                  )
                  .map((p) => (
                    <tr
                      key={`${p.exchange}-${p.symbol}`}
                      className="border-t border-[var(--border)]/50"
                    >
                      <td className="py-1.5">{p.exchange}</td>
                      <td className="py-1.5">{p.symbol}</td>
                      <td className="py-1.5 tabular-nums">{formatPrice(p.symbol, p.bid)}</td>
                      <td className="py-1.5 tabular-nums">{formatPrice(p.symbol, p.ask)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-panel)]/80 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="m-0 text-lg font-medium">Opportunity history</h2>
          <select
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
            className="rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1 text-sm"
          >
            <option value={24}>24h</option>
            <option value={72}>72h</option>
            <option value={168}>7d</option>
          </select>
        </div>

        {stats && (
          <p className="mt-2 text-xs text-[var(--muted)]">
            {stats.count} edges · avg {stats.avg_net_edge_pct.toFixed(3)}% · max{' '}
            {stats.max_net_edge_pct.toFixed(3)}%
          </p>
        )}

        {chart ? (
          <svg
            viewBox={`0 0 ${chart.w} ${chart.h}`}
            className="mt-3 w-full rounded border border-[var(--border)]/60 bg-[var(--bg)]/50"
            role="img"
            aria-label="Opportunity count over time"
          >
            <polyline
              fill="none"
              stroke="var(--accent)"
              strokeWidth="2"
              points={chart.points}
            />
          </svg>
        ) : (
          <p className="mt-3 text-sm text-[var(--muted)]">No diary data in this window yet.</p>
        )}

        <div className="mt-3 max-h-40 overflow-auto text-sm">
          {history.length === 0 ? (
            <p className="text-[var(--muted)]">Snapshots appear as edges are detected.</p>
          ) : (
            <table className="w-full min-w-[420px] border-collapse">
              <thead>
                <tr className="text-left text-[var(--muted)]">
                  <th className="py-1 font-medium">When</th>
                  <th className="py-1 font-medium">Route</th>
                  <th className="py-1 font-medium">Net %</th>
                </tr>
              </thead>
              <tbody>
                {history.slice(0, 30).map((h) => (
                  <tr key={h.id} className="border-t border-[var(--border)]/50">
                    <td className="py-1.5 text-[var(--muted)]">
                      {new Date(h.recorded_at).toLocaleTimeString()}
                    </td>
                    <td className="py-1.5">
                      {h.symbol} · {h.buy_exchange}→{h.sell_exchange}
                    </td>
                    <td className="py-1.5 text-[var(--accent)]">{h.net_edge_pct.toFixed(3)}</td>
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
