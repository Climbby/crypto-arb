import { useCallback, useEffect, useState } from 'react'
import { api, type Portfolio } from './api'
import { Header } from './components/Header'
import { PortfolioPanel } from './components/PortfolioPanel'
import { PricesAndHistory } from './components/PricesAndHistory'
import { SettingsPanel } from './components/SettingsPanel'
import { TradingViewChart } from './components/TradingViewChart'
import { useOpportunities } from './hooks/useOpportunities'
import { useTheme } from './hooks/useTheme'

export default function App() {
  const { prices, scanCount, scansLastMinute, connected, autoPaper, autoFillSeq } =
    useOpportunities()
  const { theme, toggleTheme } = useTheme()
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
        scansLastMinute={scansLastMinute}
        autoPaper={autoPaper}
        theme={theme}
        onToggleTheme={toggleTheme}
      />

      <main className="mt-8 flex flex-col gap-6">
        <TradingViewChart theme={theme} />
        <PortfolioPanel
          portfolio={portfolio}
          onChange={refreshPaper}
          refreshKey={historyKey + autoFillSeq}
        />
        <PricesAndHistory prices={prices} refreshKey={historyKey} />
        <SettingsPanel onSaved={refreshPaper} />
      </main>
    </div>
  )
}
