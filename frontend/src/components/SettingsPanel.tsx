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
  const [autoEnabled, setAutoEnabled] = useState(true)
  const [autoNotional, setAutoNotional] = useState(100)
  const [autoMinEdge, setAutoMinEdge] = useState('')
  const [autoCooldown, setAutoCooldown] = useState(12)
  const [autoMaxScan, setAutoMaxScan] = useState(3)
  const [autoMaxMin, setAutoMaxMin] = useState(20)
  const [rebalanceEnabled, setRebalanceEnabled] = useState(true)
  const [rebalanceCooldown, setRebalanceCooldown] = useState(20)
  const [rebalanceChunk, setRebalanceChunk] = useState(500)
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
      setAutoEnabled(s.auto_paper_enabled ?? true)
      setAutoNotional(s.auto_paper_notional_usdt ?? 100)
      setAutoMinEdge(
        s.auto_paper_min_net_edge_pct == null ? '' : String(s.auto_paper_min_net_edge_pct),
      )
      setAutoCooldown(s.auto_paper_cooldown_seconds ?? 12)
      setAutoMaxScan(s.auto_paper_max_per_scan ?? 3)
      setAutoMaxMin(s.auto_paper_max_per_minute ?? 20)
      setRebalanceEnabled(s.auto_rebalance_enabled ?? true)
      setRebalanceCooldown(s.auto_rebalance_cooldown_seconds ?? 20)
      setRebalanceChunk(s.auto_rebalance_usdt_chunk ?? 500)
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
        auto_paper_enabled: autoEnabled,
        auto_paper_notional_usdt: autoNotional,
        auto_paper_min_net_edge_pct: autoMinEdge.trim() === '' ? null : Number(autoMinEdge),
        auto_paper_cooldown_seconds: autoCooldown,
        auto_paper_max_per_scan: autoMaxScan,
        auto_paper_max_per_minute: autoMaxMin,
        auto_rebalance_enabled: rebalanceEnabled,
        auto_rebalance_cooldown_seconds: rebalanceCooldown,
        auto_rebalance_usdt_chunk: rebalanceChunk,
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

      <h3 className="mt-6 text-base font-medium">Auto paper</h3>
      <p className="mt-1 text-xs text-[var(--muted)]">
        Fills the best executable edge each scan (paper only). Cooldown stops the same id from
        firing every tick.
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="flex items-center gap-2 text-sm sm:col-span-2">
          <input
            type="checkbox"
            checked={autoEnabled}
            onChange={(e) => setAutoEnabled(e.target.checked)}
          />
          <span>Enable auto paper trading</span>
        </label>
        <label className="block text-sm">
          <span className="text-[var(--muted)]">Notional USDT per fill</span>
          <input
            type="number"
            step="10"
            value={autoNotional}
            onChange={(e) => setAutoNotional(Number(e.target.value))}
            className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5"
          />
        </label>
        <label className="block text-sm">
          <span className="text-[var(--muted)]">Auto min edge % (blank = board min)</span>
          <input
            type="text"
            inputMode="decimal"
            placeholder="same as board"
            value={autoMinEdge}
            onChange={(e) => setAutoMinEdge(e.target.value)}
            className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5"
          />
        </label>
        <label className="block text-sm">
          <span className="text-[var(--muted)]">Cooldown per opportunity (s)</span>
          <input
            type="number"
            step="1"
            value={autoCooldown}
            onChange={(e) => setAutoCooldown(Number(e.target.value))}
            className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5"
          />
        </label>
        <label className="block text-sm">
          <span className="text-[var(--muted)]">Max fills / scan</span>
          <input
            type="number"
            step="1"
            min={1}
            max={10}
            value={autoMaxScan}
            onChange={(e) => setAutoMaxScan(Number(e.target.value))}
            className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5"
          />
        </label>
        <label className="block text-sm">
          <span className="text-[var(--muted)]">Max fills / minute</span>
          <input
            type="number"
            step="1"
            min={1}
            max={60}
            value={autoMaxMin}
            onChange={(e) => setAutoMaxMin(Number(e.target.value))}
            className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5"
          />
        </label>
      </div>

      <h3 className="mt-6 text-base font-medium">Auto rebalance</h3>
      <p className="mt-1 text-xs text-[var(--muted)]">
        When an edge is blocked (venue out of USDT or coins), move paper inventory from the richest
        donor venue so the next scan can fill.
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="flex items-center gap-2 text-sm sm:col-span-2">
          <input
            type="checkbox"
            checked={rebalanceEnabled}
            onChange={(e) => setRebalanceEnabled(e.target.checked)}
          />
          <span>Enable auto rebalance transfers</span>
        </label>
        <label className="block text-sm">
          <span className="text-[var(--muted)]">USDT chunk size</span>
          <input
            type="number"
            step="50"
            value={rebalanceChunk}
            onChange={(e) => setRebalanceChunk(Number(e.target.value))}
            className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5"
          />
        </label>
        <label className="block text-sm">
          <span className="text-[var(--muted)]">Rebalance cooldown (s)</span>
          <input
            type="number"
            step="1"
            value={rebalanceCooldown}
            onChange={(e) => setRebalanceCooldown(Number(e.target.value))}
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
