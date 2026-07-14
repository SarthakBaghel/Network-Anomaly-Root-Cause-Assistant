import { InvestigationPage } from './pages/InvestigationPage'
import { OverviewPage } from './pages/OverviewPage'

export default function App() {
  const match = window.location.pathname.match(/^\/incidents\/([^/]+)$/)
  return match ? <InvestigationPage incidentId={decodeURIComponent(match[1])} /> : <OverviewPage />
}
