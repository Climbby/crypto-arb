import { useEffect, useState } from 'react'
import { api, type AppSettings } from '../api'

type Props = {
  onSaved: () => void
}

export function SettingsPanel({ onSaved }: Props) {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [minEdge, setMinEdge] = useState(0.05)
  const [slippage, setSlippage] = useState(5)
  const [feeBinance, setFeeBinance] = useState(0.001)
  const [feeKraken, setFeeKraken] = useState(0.0026)
  const [feeCoinbase, setFeeCoinbase] = useState(0.006)
  const [symbols, setSymbols] = useState('BTC/USDT,ETH/USDT,SOL/USDT')
  const [starting, setStarting] = useState(10000)
  const [msg, setMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void api.getSettings().then((s) => {
      setSettings(s)
      setMinEdge(s.min_net_edge_pct)
      setSlippage(s.slippage_bps)
      setFeeBinance(s.fees.binance ?? 0.001)
      setFeeKraken(s.fees.kraken ?? 0.0026)
      setFeeCoinbase(s.fees.coinbase ?? 0.006)
      setSymbols(s.watched_symbols.join(','))
      setStarting(s.paper_starting_usdt)
    })
  }, [])

  async function save() {
    setError(null)
    setMsg(null)
    try {
      const updated = await api.patchSettings({
        min_net_edge_pct: minEdge,
        slippage_bps: slippage,
        fee_binance: feeBinance,
        fee_kraken: feeKraken,
        fee_coinbase: feeCoinbase,
        watched_symbols: symbols
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
        paper_starting_usdt: starting,
      })
      setSettings(updated)
      setMsg('Settings saved')
      onSaved()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  if (!settings) {
    return (
      <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-panel)]/80 p-4 text-[var(--muted)]">
        Loading settings…
      </section>
    )
  }

  return (
    <section className="rounded-lg border border-[var(--border)] bg-[var(--bg-panel)]/80 p-4">
      <h2 className="m-0 text-lg font-medium">Settings</h2>
      <p className="mt-1 text-xs text-[var(--muted)]">
        Poll every {settings.poll_interval_seconds}s · venues:{' '}
        {settings.exchanges.join(', ')}
      </p>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <label className="block text-sm">
          <span className="text-[var(--muted)]">Min net edge %</span>
          <input
            type="number"
            step="0.01"
            value={minEdge}
            onChange={(e) => setMinEdge(Number(e.target.value))}
            className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5"
          />
        </label>
        <label className="block text-sm">
          <span className="text-[var(--muted)]">Slippage (bps per leg)</span>
          <input
            type="number"
            step="1"
            value={slippage}
            onChange={(e) => setSlippage(Number(e.target.value))}
            className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5"
          />
        </label>
        <label className="block text-sm">
          <span className="text-[var(--muted)]">Binance taker fee</span>
          <input
            type="number"
            step="0.0001"
            value={feeBinance}
            onChange={(e) => setFeeBinance(Number(e.target.value))}
            className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5"
          />
        </label>
        <label className="block text-sm">
          <span className="text-[var(--muted)]">Kraken taker fee</span>
          <input
            type="number"
            step="0.0001"
            value={feeKraken}
            onChange={(e) => setFeeKraken(Number(e.target.value))}
            className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5"
          />
        </label>
        <label className="block text-sm">
          <span className="text-[var(--muted)]">Coinbase taker fee</span>
          <input
            type="number"
            step="0.0001"
            value={feeCoinbase}
            onChange={(e) => setFeeCoinbase(Number(e.target.value))}
            className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5"
          />
        </label>
        <label className="block text-sm">
          <span className="text-[var(--muted)]">Starting USDT (on reset)</span>
          <input
            type="number"
            step="100"
            value={starting}
            onChange={(e) => setStarting(Number(e.target.value))}
            className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5"
          />
        </label>
        <label className="block text-sm sm:col-span-2">
          <span className="text-[var(--muted)]">Watched symbols (comma-separated)</span>
          <input
            type="text"
            value={symbols}
            onChange={(e) => setSymbols(e.target.value)}
            className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5"
          />
        </label>
      </div>

      {error && <p className="mt-3 text-sm text-[var(--danger)]">{error}</p>}
      {msg && <p className="mt-3 text-sm text-[var(--accent)]">{msg}</p>}

      <button
        type="button"
        onClick={() => void save()}
        className="mt-4 rounded bg-[var(--accent)] px-4 py-2 text-sm font-medium text-[#062016]"
      >
        Save settings
      </button>
    </section>
  )
}
