import { useCallback, useEffect, useState } from 'react'
import { api, type Portfolio } from './api'
import { Header } from './components/Header'
import { OpportunityBoard } from './components/OpportunityBoard'
import { PortfolioPanel } from './components/PortfolioPanel'
import { PricesAndHistory } from './components/PricesAndHistory'
import { SettingsPanel } from './components/SettingsPanel'
import { TradingViewChart } from './components/TradingViewChart'
import { useOpportunities } from './hooks/useOpportunities'

const EXCHANGES = ['binance', 'kraken', 'coinbase']

export default function App() {
  const { opportunities, prices, scanCount, connected, lastUpdateAt, feedModes, autoPaper, autoFillSeq } =
    useOpportunities()
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null)
  const [historyKey, setHistoryKey] = useState(0)

  const refreshPaper = useCallback(() => {
    void api.getPaper().then(setPortfolio)
    setHistoryKey((k) => k + 1)
  }, [])

  useEffect(() => {
    refreshPaper()
  }, [refreshPaper])

  useEffect(() => {
    if (autoFillSeq > 0) refreshPaper()
  }, [autoFillSeq, refreshPaper])

  // Refresh history periodically when scans advance
  useEffect(() => {
    if (scanCount > 0 && scanCount % 5 === 0) {
      setHistoryKey((k) => k + 1)
    }
  }, [scanCount])

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
      <Header
        connected={connected}
        scanCount={scanCount}
        lastUpdateAt={lastUpdateAt}
        autoPaper={autoPaper}
      />

      <main className="mt-8 flex flex-col gap-6">
        <OpportunityBoard opportunities={opportunities} onExecuted={refreshPaper} />
        <TradingViewChart />
        <PortfolioPanel
          portfolio={portfolio}
          exchanges={EXCHANGES}
          onChange={refreshPaper}
          refreshKey={historyKey + autoFillSeq}
        />
        <PricesAndHistory
          prices={prices}
          refreshKey={historyKey}
          lastUpdateAt={lastUpdateAt}
          feedModes={feedModes}
        />
        <SettingsPanel onSaved={refreshPaper} />
      </main>

      <footer className="mt-10 border-t border-[var(--border)] pt-4 text-xs text-[var(--muted)]">
        v1 · auto paper on edges · live trading deferred
      </footer>
    </div>
  )
}
