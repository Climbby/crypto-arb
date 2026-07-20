import { useEffect, useMemo, useState } from 'react'
import { api, type EquityPoint, type Portfolio } from '../api'
import { HoverLineChart, type ChartDatum } from './HoverLineChart'

type Props = {
  portfolio: Portfolio | null
  onChange: () => void
  refreshKey?: number
}

const EQUITY_RANGES: { label: string; hours: number | null }[] = [
  { label: '1h', hours: 1 },
  { label: '6h', hours: 6 },
  { label: '24h', hours: 24 },
  { label: '7d', hours: 168 },
  { label: 'All', hours: null },
]

type ChartTab = 'equity' | 'pnl'

type VenueEquity = {
  equity_usdt: number
  daily_pct: number | null
}

const TRADE_LOG_LIMIT = 40
const TRANSFER_LOG_LIMIT = 20

export function PortfolioPanel({ portfolio, onChange: _onChange, refreshKey = 0 }: Props) {
  const [equityNow, setEquityNow] = useState<number | null>(null)
  const [pnlNow, setPnlNow] = useState<number | null>(null)
  const [equityHist, setEquityHist] = useState<EquityPoint[]>([])
  const [venues, setVenues] = useState<Record<string, VenueEquity>>({})
  const [last24h, setLast24h] = useState<{
    realized_pnl_usdt: number
    pct: number | null
  } | null>(null)
  const [hours, setHours] = useState<number | null>(null)
  const [chartTab, setChartTab] = useState<ChartTab>('equity')

  useEffect(() => {
    // Point budget for the chart — backend downsamples evenly across the window
    const limit = 800
    void api
      .getEquity(limit, hours)
      .then((r) => {
        setEquityNow(r.current.equity_usdt)
        setPnlNow(r.current.realized_pnl_usdt)
        setEquityHist(r.history)
        setVenues(r.venues ?? {})
        setLast24h(r.last_24h ?? null)
      })
      .catch(() => {
        /* ignore */
      })
  }, [refreshKey, hours, portfolio?.realized_pnl_usdt, portfolio?.trades.length])

  const shortTime = useMemo(() => {
    return (isoOrMs: string | number) => {
      const d = typeof isoOrMs === 'number' ? new Date(isoOrMs) : new Date(isoOrMs)
      if (hours == null || hours >= 24) {
        return d.toLocaleString(undefined, {
          month: 'short',
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
        })
      }
      return d.toLocaleTimeString(undefined, {
        hour: '2-digit',
        minute: '2-digit',
      })
    }
  }, [hours])

  const hoverTime = useMemo(() => {
    return (iso: string) =>
      new Date(iso).toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })
  }, [])

  const chartData: ChartDatum[] = useMemo(() => {
    const key = chartTab === 'equity' ? 'equity_usdt' : 'realized_pnl_usdt'
    return equityHist.map((p) => ({
      y: p[key],
      t: new Date(p.recorded_at).getTime(),
      axisLabel: shortTime(p.recorded_at),
      label: hoverTime(p.recorded_at),
      valueLabel: p[key].toFixed(2),
    }))
  }, [equityHist, chartTab, shortTime, hoverTime])

  const timeDomain = useMemo(() => {
    if (chartData.length < 2) return null
    const endMs = Date.now()
    if (hours != null && hours > 0) {
      return { startMs: endMs - hours * 3600_000, endMs }
    }
    const first = chartData[0].t
    if (first == null) return null
    return { startMs: first, endMs }
  }, [chartData, hours])

  const liveCurrent =
    chartTab === 'equity'
      ? (equityNow ?? (chartData.length ? chartData[chartData.length - 1].y : null))
      : (pnlNow ?? portfolio?.realized_pnl_usdt ?? (chartData.length ? chartData[chartData.length - 1].y : null))

  const formatMoney = (v: number) =>
    v.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })

  const realized = portfolio?.realized_pnl_usdt ?? pnlNow ?? 0
  const dayPnl = last24h?.realized_pnl_usdt
  const dayPct = last24h?.pct
  const dayPositive = dayPnl == null ? true : dayPnl >= 0

  const trades = (portfolio?.trades ?? []).slice(0, TRADE_LOG_LIMIT)
  const transfers = (portfolio?.transfers ?? []).slice(0, TRANSFER_LOG_LIMIT)

  return (
    <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-panel)]/80 p-4">
      <div className="mb-3">
        <h2 className="m-0 text-lg font-medium">Paper portfolio</h2>
        <p className="m-0 mt-1 text-xs text-[var(--muted)]">
          Marked equity:{' '}
          <span className="text-[var(--accent)] tabular-nums">
            {formatMoney(equityNow ?? 0)} USDT
          </span>
          {' · '}
          Realized PnL{' '}
          <span className="text-[var(--accent)] tabular-nums">
            {realized >= 0 ? '+' : ''}
            {formatMoney(realized)} USDT
          </span>
          {dayPnl != null ? (
            <>
              {' · '}
              Last 24h profit{' '}
              <span
                className={`tabular-nums ${
                  dayPositive ? 'text-[var(--accent)]' : 'text-[var(--danger)]'
                }`}
              >
                {dayPositive ? '+' : '-'}${formatMoney(Math.abs(dayPnl))}
                {dayPct != null ? (
                  <>
                    {' '}
                    ({dayPositive ? '+' : ''}
                    {dayPct.toFixed(2)}%)
                  </>
                ) : null}
              </span>
            </>
          ) : null}
        </p>
      </div>

      <div className="mb-4 rounded border border-[var(--border)]/80 bg-[var(--bg)]/40 p-3">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <div
            className="inline-flex rounded border border-[var(--border)] p-0.5"
            role="tablist"
            aria-label="Chart series"
          >
            {(
              [
                { id: 'equity', label: 'Equity' },
                { id: 'pnl', label: 'PnL' },
              ] as const
            ).map((tab) => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={chartTab === tab.id}
                onClick={() => setChartTab(tab.id)}
                className={`rounded px-2.5 py-1 text-xs font-medium ${
                  chartTab === tab.id
                    ? 'bg-[var(--accent)] text-[var(--on-accent)]'
                    : 'text-[var(--muted)] hover:text-[var(--text)]'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap gap-1">
            {EQUITY_RANGES.map((r) => (
              <button
                key={r.label}
                type="button"
                onClick={() => setHours(r.hours)}
                className={`rounded px-2 py-0.5 text-xs ${
                  hours === r.hours
                    ? 'bg-[var(--accent)] text-[var(--on-accent)]'
                    : 'border border-[var(--border)] text-[var(--muted)] hover:text-[var(--text)]'
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
        {chartData.length >= 2 ? (
          <HoverLineChart
            data={chartData}
            height={180}
            ariaLabel={
              chartTab === 'equity' ? 'Paper equity over time' : 'Realized PnL over time'
            }
            className="rounded border border-[var(--border)]/40 bg-[var(--bg)]/30"
            showLevels
            currentValue={liveCurrent}
            formatLevel={formatMoney}
            timeDomain={timeDomain}
            formatTimeAxis={shortTime}
          />
        ) : (
          <p className="m-0 text-sm text-[var(--muted)]">
            Not enough snapshots in this window yet — try a wider range or wait for the next fill
            / heartbeat.
          </p>
        )}
      </div>

      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        {Object.entries(portfolio?.by_venue ?? {}).map(([venue, assets]) => {
          const v = venues[venue]
          const daily = v?.daily_pct
          return (
            <div key={venue} className="rounded border border-[var(--border)] bg-[var(--bg)]/60 p-3">
              <p className="m-0 text-xs uppercase tracking-wider text-[var(--muted)]">{venue}</p>
              <p className="m-0 mt-1 text-sm">
                Equity{' '}
                <span className="font-medium text-[var(--accent)] tabular-nums">
                  {v ? formatMoney(v.equity_usdt) : '—'} USDT
                </span>
              </p>
              <p className="m-0 mt-0.5 text-xs text-[var(--muted)]">
                24h{' '}
                {daily == null ? (
                  <span>—</span>
                ) : (
                  <span
                    className={`tabular-nums ${
                      daily >= 0 ? 'text-[var(--accent)]' : 'text-[var(--danger)]'
                    }`}
                  >
                    {daily >= 0 ? '+' : ''}
                    {daily.toFixed(2)}%
                  </span>
                )}
              </p>
              <ul className="mt-2 space-y-1 text-sm">
                {Object.entries(assets).map(([a, amt]) => (
                  <li key={a} className="flex justify-between gap-2">
                    <span className="text-[var(--muted)]">{a}</span>
                    <span>{amt < 1 ? amt.toFixed(6) : amt.toFixed(2)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <h3 className="m-0 mb-2 text-sm font-medium text-[var(--muted)]">Trade log</h3>
          <div className="max-h-48 overflow-auto text-sm">
            {trades.length === 0 ? (
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
                  {trades.map((t) => (
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
            {transfers.length === 0 ? (
              <p className="text-[var(--muted)]">No transfers yet.</p>
            ) : (
              <table className="w-full min-w-[420px] border-collapse">
                <thead>
                  <tr className="text-left text-[var(--muted)]">
                    <th className="py-1 font-medium">Time</th>
                    <th className="py-1 font-medium">Move</th>
                    <th className="py-1 font-medium">Amount</th>
                    <th className="py-1 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {transfers.map((t) => {
                    const pending = t.status === 'pending'
                    const net = t.net_amount ?? t.amount
                    return (
                      <tr key={t.id} className="border-t border-[var(--border)]/50">
                        <td className="py-1.5 text-[var(--muted)]">
                          {new Date(t.transferred_at).toLocaleTimeString()}
                        </td>
                        <td className="py-1.5">
                          {t.asset} · {t.from_venue}→{t.to_venue}
                          {t.fee_amount ? ` · fee ${Number(t.fee_amount).toPrecision(4)}` : ''}
                        </td>
                        <td className="py-1.5">{Number(net).toFixed(6)}</td>
                        <td className="py-1.5 text-[var(--muted)]">
                          {pending
                            ? `in transit${t.arrives_at ? ` · ETA ${new Date(t.arrives_at).toLocaleTimeString()}` : ''}`
                            : 'settled'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </div>
          {portfolio?.in_transit && Object.keys(portfolio.in_transit).length > 0 ? (
            <p className="m-0 mt-2 text-xs text-[var(--muted)]">
              In transit:{' '}
              {Object.entries(portfolio.in_transit)
                .map(([a, v]) => `${a} ${Number(v).toPrecision(6)}`)
                .join(' · ')}
            </p>
          ) : null}
        </div>
      </div>
    </section>
  )
}
