import { InvestigationPage } from './pages/InvestigationPage'
import { OverviewPage } from './pages/OverviewPage'

export default function App() {
  return window.location.pathname.startsWith('/incidents/') ? <InvestigationPage /> : <OverviewPage />
}

