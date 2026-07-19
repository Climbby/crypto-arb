import { useEffect, useRef, useState } from 'react'
import { api, type Opportunity, type Tick, wsUrl } from '../api'

export type AutoPaperStatus = {
  enabled: boolean
  notional_usdt: number
  fills_total: number
  last_result: {
    ok?: boolean
    opp_id?: string
    symbol?: string
    pnl_usdt?: number
    reason?: string
    at?: number
  } | null
}

export type AutoFill = {
  ok: boolean
  opp_id: string
  symbol: string
  pnl_usdt?: number
  notional_usdt?: number
}

type Snapshot = {
  opportunities: Opportunity[]
  prices: Tick[]
  scanCount: number
  connected: boolean
  lastUpdateAt: number | null
  feedModes: Record<string, string>
  autoPaper: AutoPaperStatus | null
  autoFillSeq: number
}

export function useOpportunities(): Snapshot {
  const [opportunities, setOpportunities] = useState<Opportunity[]>([])
  const [prices, setPrices] = useState<Tick[]>([])
  const [scanCount, setScanCount] = useState(0)
  const [connected, setConnected] = useState(false)
  const [lastUpdateAt, setLastUpdateAt] = useState<number | null>(null)
  const [feedModes, setFeedModes] = useState<Record<string, string>>({})
  const [autoPaper, setAutoPaper] = useState<AutoPaperStatus | null>(null)
  const [autoFillSeq, setAutoFillSeq] = useState(0)
  const wsRef = useRef<WebSocket | null>(null)
  const retryTimer = useRef<number | null>(null)
  const intentionalClose = useRef(false)
  const retryCount = useRef(0)

  useEffect(() => {
    intentionalClose.current = false

    const applySnapshot = (data: {
      type?: string
      opportunities?: Opportunity[]
      prices?: Tick[]
      scan_count?: number
      feed_modes?: Record<string, string>
      auto_paper?: AutoPaperStatus
      auto_fills?: AutoFill[]
    }) => {
      if (data.type && data.type !== 'opportunities') return
      if (data.opportunities) setOpportunities(data.opportunities)
      if (data.prices) setPrices(data.prices)
      if (typeof data.scan_count === 'number') setScanCount(data.scan_count)
      if (data.feed_modes) setFeedModes(data.feed_modes)
      if (data.auto_paper) setAutoPaper(data.auto_paper)
      if (data.auto_fills && data.auto_fills.length > 0) {
        setAutoFillSeq((n) => n + 1)
      }
      setLastUpdateAt(Date.now())
    }

    const clearRetry = () => {
      if (retryTimer.current != null) {
        window.clearTimeout(retryTimer.current)
        retryTimer.current = null
      }
    }

    const connect = () => {
      clearRetry()
      if (wsRef.current) {
        try {
          wsRef.current.close()
        } catch {
          /* ignore */
        }
      }

      const ws = new WebSocket(wsUrl())
      wsRef.current = ws

      ws.onopen = () => {
        setConnected(true)
        retryCount.current = 0
      }

      ws.onmessage = (ev) => {
        try {
          applySnapshot(JSON.parse(ev.data as string))
        } catch {
          /* ignore malformed */
        }
      }

      ws.onerror = () => {
        // onclose will handle reconnect
      }

      ws.onclose = () => {
        setConnected(false)
        if (intentionalClose.current) return
        const delay = Math.min(8000, 400 * 2 ** retryCount.current)
        retryCount.current += 1
        retryTimer.current = window.setTimeout(connect, delay)
      }
    }

    connect()

    // REST fallback so the board keeps moving even if WS stalls
    const poll = window.setInterval(() => {
      void Promise.all([
        api.getPrices(),
        api.getOpportunities(),
        fetch(`${import.meta.env.DEV ? '/api' : ''}/health`).then((r) => r.json()),
      ])
        .then(([priceRes, oppRes, health]) => {
          applySnapshot({
            type: 'opportunities',
            prices: priceRes.prices,
            opportunities: oppRes.opportunities,
            scan_count: typeof health.scan_count === 'number' ? health.scan_count : undefined,
            auto_paper: health.auto_paper,
          })
        })
        .catch(() => {
          /* backend briefly down */
        })
    }, 2000)

    return () => {
      intentionalClose.current = true
      clearRetry()
      window.clearInterval(poll)
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [])

  return {
    opportunities,
    prices,
    scanCount,
    connected,
    lastUpdateAt,
    feedModes,
    autoPaper,
    autoFillSeq,
  }
}
