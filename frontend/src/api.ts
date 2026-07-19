export type Tick = {
  exchange: string
  symbol: string
  bid: number
  ask: number
  last: number | null
  mid: number
  timestamp: string
}

export type Opportunity = {
  id: string
  symbol: string
  buy_exchange: string
  sell_exchange: string
  buy_price: number
  sell_price: number
  raw_edge_pct: number
  net_edge_pct: number
  buy_fee_pct: number
  sell_fee_pct: number
  slippage_pct: number
  detected_at: string
  theoretical: boolean
}

export type PaperTrade = {
  id: number
  opp_id: string
  symbol: string
  buy_exchange: string
  sell_exchange: string
  quantity: number
  buy_price: number
  sell_price: number
  net_edge_pct: number
  pnl_usdt: number
  executed_at: string
}

export type PaperTransfer = {
  id: number
  asset: string
  from_venue: string
  to_venue: string
  amount: number
  delayed: number | boolean
  transferred_at: string
}

export type Portfolio = {
  balances: { venue: string; asset: string; amount: number }[]
  by_venue: Record<string, Record<string, number>>
  trades: PaperTrade[]
  transfers: PaperTransfer[]
  realized_pnl_usdt: number
  starting_usdt: number
  note: string
}

export type AppSettings = {
  min_net_edge_pct: number
  slippage_bps: number
  fees: Record<string, number>
  watched_symbols: string[]
  exchanges: string[]
  paper_starting_usdt: number
  poll_interval_seconds: number
}

export type HistoryRow = {
  id: number
  opp_id: string
  symbol: string
  buy_exchange: string
  sell_exchange: string
  buy_price: number
  sell_price: number
  raw_edge_pct: number
  net_edge_pct: number
  recorded_at: string
}

const API_BASE = import.meta.env.VITE_API_BASE ?? (import.meta.env.DEV ? '/api' : '')

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? JSON.stringify(body)
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return res.json() as Promise<T>
}

export const api = {
  getOpportunities: () =>
    request<{ opportunities: Opportunity[]; note: string }>('/opportunities'),
  getPrices: () => request<{ prices: Tick[] }>('/prices'),
  getHistory: (limit = 80) =>
    request<{ history: HistoryRow[] }>(`/opportunities/history?limit=${limit}`),
  getSettings: () => request<AppSettings>('/settings'),
  patchSettings: (body: Partial<{
    min_net_edge_pct: number
    slippage_bps: number
    fee_binance: number
    fee_kraken: number
    fee_coinbase: number
    watched_symbols: string[]
    paper_starting_usdt: number
  }>) =>
    request<AppSettings>('/settings', {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  getPaper: () => request<Portfolio>('/paper'),
  resetPaper: () => request<Portfolio>('/paper/reset', { method: 'POST' }),
  execute: (opportunity_id: string, notional_usdt: number) =>
    request<{ trade: PaperTrade; portfolio: Portfolio }>('/paper/execute', {
      method: 'POST',
      body: JSON.stringify({ opportunity_id, notional_usdt }),
    }),
  transfer: (body: {
    asset: string
    from_venue: string
    to_venue: string
    amount: number
    delayed: boolean
  }) =>
    request<{ transfer: PaperTransfer; portfolio: Portfolio; note: string }>(
      '/paper/transfer',
      { method: 'POST', body: JSON.stringify(body) },
    ),
}

export function wsUrl(): string {
  const custom = import.meta.env.VITE_WS_URL as string | undefined
  if (custom) return custom
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  // Dev: Vite proxies /ws → backend. Prod: same origin as the API.
  return `${proto}://${window.location.host}/ws/opportunities`
}
