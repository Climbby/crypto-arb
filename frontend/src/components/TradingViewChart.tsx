import { useEffect, useId, useRef, useState } from 'react'

declare global {
  interface Window {
    TradingView?: {
      widget: new (config: Record<string, unknown>) => unknown
    }
  }
}

const SYMBOLS = [
  { label: 'BTC/USDT', base: 'BTC' },
  { label: 'ETH/USDT', base: 'ETH' },
  { label: 'SOL/USDT', base: 'SOL' },
] as const

const VENUES = [
  { id: 'binance', label: 'Binance', tv: (base: string) => `BINANCE:${base}USDT` },
  { id: 'kraken', label: 'Kraken', tv: (base: string) => `KRAKEN:${base}USDT` },
  { id: 'coinbase', label: 'Coinbase', tv: (base: string) => `COINBASE:${base}USD` },
] as const

const INTERVALS = [
  { id: '1', label: '1m' },
  { id: '5', label: '5m' },
  { id: '15', label: '15m' },
  { id: '60', label: '1h' },
  { id: '240', label: '4h' },
  { id: 'D', label: '1D' },
] as const

let tvScriptPromise: Promise<void> | null = null

function loadTradingViewScript(): Promise<void> {
  if (window.TradingView) return Promise.resolve()
  if (tvScriptPromise) return tvScriptPromise
  tvScriptPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>('script[data-tv-widget]')
    if (existing) {
      existing.addEventListener('load', () => resolve())
      existing.addEventListener('error', () => reject(new Error('TradingView script failed')))
      return
    }
    const script = document.createElement('script')
    script.src = 'https://s3.tradingview.com/tv.js'
    script.async = true
    script.dataset.tvWidget = '1'
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('TradingView script failed'))
    document.head.appendChild(script)
  })
  return tvScriptPromise
}

export function TradingViewChart() {
  const reactId = useId().replace(/:/g, '')
  const containerId = `tv_chart_${reactId}`
  const containerRef = useRef<HTMLDivElement>(null)
  const [pair, setPair] = useState<(typeof SYMBOLS)[number]>(SYMBOLS[0])
  const [venue, setVenue] = useState<(typeof VENUES)[number]>(VENUES[0])
  const [timeframe, setTimeframe] = useState<(typeof INTERVALS)[number]>(INTERVALS[2])
  const [error, setError] = useState<string | null>(null)

  const tvSymbol = venue.tv(pair.base)

  useEffect(() => {
    let cancelled = false
    setError(null)

    void loadTradingViewScript()
      .then(() => {
        if (cancelled || !containerRef.current || !window.TradingView) return
        containerRef.current.innerHTML = ''
        const host = document.createElement('div')
        host.id = containerId
        host.style.height = '100%'
        host.style.width = '100%'
        containerRef.current.appendChild(host)

        new window.TradingView.widget({
          autosize: true,
          symbol: tvSymbol,
          interval: timeframe.id,
          timezone: 'Etc/UTC',
          theme: 'dark',
          style: '1',
          locale: 'en',
          toolbar_bg: '#121a24',
          enable_publishing: false,
          hide_top_toolbar: false,
          hide_legend: false,
          save_image: false,
          container_id: containerId,
          backgroundColor: '#0c1117',
          gridColor: 'rgba(36, 48, 65, 0.6)',
          allow_symbol_change: true,
          withdateranges: true,
        })
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load TradingView')
        }
      })

    return () => {
      cancelled = true
      if (containerRef.current) containerRef.current.innerHTML = ''
    }
  }, [tvSymbol, timeframe.id, containerId])

  return (
    <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-panel)]/80 p-4">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="m-0 text-lg font-medium">TradingView chart</h2>
          <p className="m-0 mt-1 text-xs text-[var(--muted)]">
            Embedded market chart · {tvSymbol}
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-sm">
          <select
            value={pair.label}
            onChange={(e) => {
              const next = SYMBOLS.find((s) => s.label === e.target.value)
              if (next) setPair(next)
            }}
            className="rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5"
          >
            {SYMBOLS.map((s) => (
              <option key={s.label} value={s.label}>
                {s.label}
              </option>
            ))}
          </select>
          <select
            value={venue.id}
            onChange={(e) => {
              const next = VENUES.find((v) => v.id === e.target.value)
              if (next) setVenue(next)
            }}
            className="rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5"
          >
            {VENUES.map((v) => (
              <option key={v.id} value={v.id}>
                {v.label}
              </option>
            ))}
          </select>
          <select
            value={timeframe.id}
            onChange={(e) => {
              const next = INTERVALS.find((i) => i.id === e.target.value)
              if (next) setTimeframe(next)
            }}
            className="rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5"
          >
            {INTERVALS.map((i) => (
              <option key={i.id} value={i.id}>
                {i.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error ? (
        <p className="rounded border border-[var(--danger)]/40 bg-[var(--danger)]/10 px-3 py-2 text-sm text-[var(--danger)]">
          {error}
        </p>
      ) : (
        <div
          ref={containerRef}
          className="h-[420px] w-full overflow-hidden rounded border border-[var(--border)] bg-[var(--bg)]"
        />
      )}
    </section>
  )
}
