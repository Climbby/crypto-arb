import { useEffect, useRef, useState } from 'react'
import { api, type HistoryRow, type Tick } from '../api'

type Props = {
  prices: Tick[]
  refreshKey: number
  lastUpdateAt: number | null
}

function formatPrice(symbol: string, value: number): string {
  if (symbol.startsWith('SOL')) return value.toFixed(4)
  if (symbol.startsWith('ETH')) return value.toFixed(3)
  return value.toFixed(2)
}

export function PricesAndHistory({ prices, refreshKey, lastUpdateAt }: Props) {
  const [history, setHistory] = useState<HistoryRow[]>([])
  const [now, setNow] = useState(Date.now())
  const prevRef = useRef<Record<string, { bid: number; ask: number }>>({})
  const [flashes, setFlashes] = useState<Record<string, 'up' | 'down'>>({})

  useEffect(() => {
    void api.getHistory(60).then((r) => setHistory(r.history))
  }, [refreshKey])

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [])

  useEffect(() => {
    const nextFlashes: Record<string, 'up' | 'down'> = {}
    for (const p of prices) {
      const key = `${p.exchange}:${p.symbol}`
      const prev = prevRef.current[key]
      if (prev) {
        if (p.bid > prev.bid) nextFlashes[`${key}:bid`] = 'up'
        else if (p.bid < prev.bid) nextFlashes[`${key}:bid`] = 'down'
        if (p.ask > prev.ask) nextFlashes[`${key}:ask`] = 'up'
        else if (p.ask < prev.ask) nextFlashes[`${key}:ask`] = 'down'
      }
      prevRef.current[key] = { bid: p.bid, ask: p.ask }
    }
    if (Object.keys(nextFlashes).length > 0) {
      setFlashes(nextFlashes)
      const t = window.setTimeout(() => setFlashes({}), 700)
      return () => window.clearTimeout(t)
    }
  }, [prices])

  const ageSec =
    lastUpdateAt == null ? null : Math.max(0, Math.floor((now - lastUpdateAt) / 1000))

  return (
    <section className="grid gap-4 lg:grid-cols-2">
      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-panel)]/80 p-4">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="m-0 text-lg font-medium">Live prices</h2>
          <p className="m-0 text-xs text-[var(--muted)]">
            {ageSec == null
              ? 'waiting…'
              : ageSec === 0
                ? 'updated just now'
                : `updated ${ageSec}s ago`}
          </p>
        </div>
        <div className="mt-3 max-h-64 overflow-auto text-sm">
          {prices.length === 0 ? (
            <p className="text-[var(--muted)]">Waiting for first poll…</p>
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
                {prices
                  .slice()
                  .sort(
                    (a, b) =>
                      a.symbol.localeCompare(b.symbol) || a.exchange.localeCompare(b.exchange),
                  )
                  .map((p) => {
                    const key = `${p.exchange}:${p.symbol}`
                    const bidFlash = flashes[`${key}:bid`]
                    const askFlash = flashes[`${key}:ask`]
                    return (
                      <tr key={key} className="border-t border-[var(--border)]/50">
                        <td className="py-1.5">{p.exchange}</td>
                        <td className="py-1.5">{p.symbol}</td>
                        <td
                          className={`py-1.5 tabular-nums transition-colors ${
                            bidFlash === 'up'
                              ? 'text-[var(--accent)]'
                              : bidFlash === 'down'
                                ? 'text-[var(--danger)]'
                                : ''
                          }`}
                        >
                          {formatPrice(p.symbol, p.bid)}
                        </td>
                        <td
                          className={`py-1.5 tabular-nums transition-colors ${
                            askFlash === 'up'
                              ? 'text-[var(--accent)]'
                              : askFlash === 'down'
                                ? 'text-[var(--danger)]'
                                : ''
                          }`}
                        >
                          {formatPrice(p.symbol, p.ask)}
                        </td>
                      </tr>
                    )
                  })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-panel)]/80 p-4">
        <h2 className="m-0 text-lg font-medium">Opportunity history</h2>
        <div className="mt-3 max-h-64 overflow-auto text-sm">
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
                {history.map((h) => (
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
