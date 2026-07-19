import { useEffect, useState } from 'react'

type Props = {
  connected: boolean
  scanCount: number
  lastUpdateAt: number | null
}

export function Header({ connected, scanCount, lastUpdateAt }: Props) {
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [])

  const ageSec =
    lastUpdateAt == null ? null : Math.max(0, Math.floor((now - lastUpdateAt) / 1000))

  return (
    <header className="flex flex-wrap items-end justify-between gap-4 border-b border-[var(--border)] pb-5">
      <div>
        <p className="m-0 text-xs tracking-[0.22em] uppercase text-[var(--muted)]">
          Cross-exchange · theoretical edges
        </p>
        <h1 className="m-0 mt-1 text-3xl font-semibold tracking-tight text-[var(--text)] sm:text-4xl">
          Arb<span className="text-[var(--accent)]">Watch</span>
        </h1>
        <p className="mt-2 max-w-xl text-sm text-[var(--muted)]">
          Live scanner + paper trader. Edges include fees and slippage estimates — not executable
          profit after latency, depth, or transfers.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-4 text-sm text-[var(--muted)]">
        <span className="inline-flex items-center gap-2">
          <span
            className={`h-2 w-2 rounded-full ${connected ? 'bg-[var(--accent)]' : 'bg-[var(--danger)]'}`}
          />
          {connected ? 'Live' : 'Reconnecting'}
        </span>
        <span>Scans: {scanCount}</span>
        <span>
          {ageSec == null ? 'No ticks yet' : ageSec === 0 ? 'Tick: now' : `Tick: ${ageSec}s ago`}
        </span>
      </div>
    </header>
  )
}
