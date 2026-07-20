import { useEffect, useMemo, useState } from 'react'
import { api, type Stats, type Tick } from '../api'
import { HoverLineChart, type ChartDatum } from './HoverLineChart'

type Props = {
  prices: Tick[]
  refreshKey: number
}

const MAJORS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT'] as const

function formatPrice(symbol: string, value: number): string {
  if (symbol.includes('SOL') && symbol.includes('USDT')) return value.toFixed(4)
  if (symbol.includes('ETH') && symbol.includes('USDT')) return value.toFixed(3)
  if (symbol.includes('/BTC') || symbol.includes('/ETH')) return value.toFixed(6)
  return value.toFixed(2)
}

type TopEdgeRow = {
  symbol: string
  buy_exchange: string
  sell_exchange: string
  net_edge_pct: number
  recorded_at: string
  count: number
}

function groupTopEdges(
  top: { symbol: string; buy_exchange: string; sell_exchange: string; net_edge_pct: number; recorded_at: string }[],
): TopEdgeRow[] {
  const map = new Map<string, TopEdgeRow>()
  for (const h of top) {
    // Only collapse exact duplicates: same route AND same displayed net %
    const netKey = h.net_edge_pct.toFixed(3)
    const key = `${h.symbol}|${h.buy_exchange}|${h.sell_exchange}|${netKey}`
    const existing = map.get(key)
    if (!existing) {
      map.set(key, { ...h, count: 1 })
      continue
    }
    existing.count += 1
    // Keep the most recent timestamp for the group
    if (h.recorded_at > existing.recorded_at) {
      existing.recorded_at = h.recorded_at
    }
  }
  return [...map.values()].sort((a, b) => b.net_edge_pct - a.net_edge_pct)
}

export function PricesAndHistory({ prices, refreshKey }: Props) {
  const [stats, setStats] = useState<Stats | null>(null)
  const [hours, setHours] = useState(24)

  useEffect(() => {
    void api.getStats(hours).then(setStats).catch(() => setStats(null))
  }, [refreshKey, hours])

  const historyChartData: ChartDatum[] = useMemo(() => {
    const buckets = stats?.buckets ?? []
    return buckets.map((b) => {
      const count = Number(b.count) || 0
      const avg = Number(b.avg_net) || 0
      const maxNet = Number(b.max_net) || 0
      const when = b.bucket ? new Date(b.bucket).toLocaleString() : 'bucket'
      return {
        y: count,
        label: `${when} · avg ${avg.toFixed(3)}% · max ${maxNet.toFixed(3)}%`,
        valueLabel: `${count} edges`,
      }
    })
  }, [stats])

  const topGrouped = useMemo(() => groupTopEdges(stats?.top ?? []), [stats])

  const bySymbol = useMemo(() => {
    const map: Record<string, Tick[]> = {}
    for (const p of prices) {
      if (!MAJORS.includes(p.symbol as (typeof MAJORS)[number])) continue
      ;(map[p.symbol] ??= []).push(p)
    }
    for (const sym of Object.keys(map)) {
      map[sym].sort((a, b) => a.exchange.localeCompare(b.exchange))
    }
    return map
  }, [prices])

  return (
    <section className="grid gap-4 lg:grid-cols-2">
      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-panel)]/80 p-4">
        <h2 className="m-0 text-lg font-medium">Live prices</h2>

        <div className="mt-4 space-y-4">
          {MAJORS.every((s) => !(bySymbol[s]?.length)) ? (
            <p className="text-sm text-[var(--muted)]">Waiting for first tick…</p>
          ) : (
            MAJORS.map((symbol) => {
              const rows = bySymbol[symbol] ?? []
              if (rows.length === 0) return null
              const bestBid = Math.max(...rows.map((r) => r.bid))
              const bestAskVal = Math.min(...rows.map((r) => r.ask))
              const spreadHint =
                bestBid > 0 && bestAskVal > 0
                  ? ((bestBid - bestAskVal) / bestAskVal) * 100
                  : null
              return (
                <div key={symbol} className="rounded border border-[var(--border)]/70 bg-[var(--bg)]/40 p-3">
                  <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
                    <h3 className="m-0 text-sm font-medium">{symbol}</h3>
                    {spreadHint != null && (
                      <p className="m-0 text-xs text-[var(--muted)]">
                        raw cross gap{' '}
                        <span
                          className={
                            spreadHint > 0 ? 'text-[var(--accent)]' : 'text-[var(--muted)]'
                          }
                        >
                          {spreadHint >= 0 ? '+' : ''}
                          {spreadHint.toFixed(3)}%
                        </span>{' '}
                        (best bid − best ask, before fees)
                      </p>
                    )}
                  </div>
                  <table className="w-full border-collapse text-sm">
                    <thead>
                      <tr className="text-left text-[var(--muted)]">
                        <th className="py-1 font-medium">Venue</th>
                        <th className="py-1 font-medium">Bid</th>
                        <th className="py-1 font-medium">Ask</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((p) => {
                        const isBestBid = p.bid === bestBid
                        const isBestAsk = p.ask === bestAskVal
                        return (
                          <tr key={`${p.exchange}-${p.symbol}`} className="border-t border-[var(--border)]/50">
                            <td className="py-1.5">{p.exchange}</td>
                            <td
                              className={`py-1.5 tabular-nums ${isBestBid ? 'font-semibold text-[var(--sell)]' : ''}`}
                              title={isBestBid ? 'Best bid (highest)' : undefined}
                            >
                              {formatPrice(symbol, p.bid)}
                              {isBestBid ? ' · best' : ''}
                            </td>
                            <td
                              className={`py-1.5 tabular-nums ${isBestAsk ? 'font-semibold text-[var(--buy)]' : ''}`}
                              title={isBestAsk ? 'Best ask (lowest)' : undefined}
                            >
                              {formatPrice(symbol, p.ask)}
                              {isBestAsk ? ' · best' : ''}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )
            })
          )}
        </div>
      </div>

      <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-panel)]/80 p-4">
        <div>
          <h2 className="m-0 text-lg font-medium">Edge activity</h2>
          <p className="m-0 mt-1 text-xs text-[var(--muted)]">
            How often theoretical edges appeared (not trades).
          </p>
        </div>

        <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
          <p className="m-0 text-xs text-[var(--muted)]">
            {stats
              ? `${stats.count} detections · avg ${stats.avg_net_edge_pct.toFixed(3)}% · max ${stats.max_net_edge_pct.toFixed(3)}%`
              : 'Loading…'}
          </p>
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

        {historyChartData.length > 0 ? (
          <HoverLineChart
            data={historyChartData}
            height={120}
            ariaLabel="Edge detections over time"
            className="mt-3 rounded border border-[var(--border)]/60 bg-[var(--bg)]/50"
          />
        ) : (
          <p className="mt-3 text-sm text-[var(--muted)]">No edge diary data in this window yet.</p>
        )}

        <h3 className="m-0 mt-4 mb-2 text-sm font-medium text-[var(--muted)]">
          Top edges this window
        </h3>
        <div className="max-h-[min(28rem,50vh)] overflow-auto text-sm">
          {topGrouped.length === 0 ? (
            <p className="text-[var(--muted)]">No top edges yet for this range.</p>
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
                {topGrouped.map((h) => (
                  <tr
                    key={`${h.symbol}-${h.buy_exchange}-${h.sell_exchange}`}
                    className="border-t border-[var(--border)]/50"
                  >
                    <td className="py-1.5 text-[var(--muted)]">
                      {new Date(h.recorded_at).toLocaleString()}
                    </td>
                    <td className="py-1.5">
                      {h.symbol} · {h.buy_exchange}→{h.sell_exchange}
                      {h.count > 1 ? ` (x${h.count})` : ''}
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
