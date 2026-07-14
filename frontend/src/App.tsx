import { InvestigationPage } from "./pages/InvestigationPage";
import { OverviewPage } from "./pages/OverviewPage";

export default function App() {
  const path = window.location.pathname;
  const incidentMatch = path.match(/^\/incidents\/([^/]+)$/);

  if (incidentMatch) {
    return <InvestigationPage incidentId={incidentMatch[1]} />;
  }

  return <OverviewPage />;
}
