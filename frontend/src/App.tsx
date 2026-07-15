import { AppShell } from "./components/layout/AppShell";
import { InvestigationPage } from "./pages/InvestigationPage";
import { OverviewPage } from "./pages/OverviewPage";

export default function App() {
  const path = window.location.pathname;
  const incidentMatch = path.match(/^\/incidents\/([^/]+)$/);

  return (
    <AppShell>
      {incidentMatch ? (
        <InvestigationPage incidentId={incidentMatch[1]} />
      ) : (
        <OverviewPage />
      )}
    </AppShell>
  );
}
