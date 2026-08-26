import { useEffect, useState } from "react";
import { AppShell, navigate } from "./components/AppShell";
import { Button } from "./components/Ui";
import { EvaluationsPage } from "./pages/EvaluationsPage";
import { KnowledgeBasePage } from "./pages/KnowledgeBasePage";
import { OverviewPage } from "./pages/OverviewPage";
import { RequestConsolePage } from "./pages/RequestConsolePage";
import { ReviewQueuePage } from "./pages/ReviewQueuePage";

const ROUTES = {
  "/": { title: "Operations overview", component: OverviewPage },
  "/console": { title: "Request Console", component: RequestConsolePage },
  "/reviews": { title: "Review Queue", component: ReviewQueuePage },
  "/knowledge": { title: "Knowledge Base", component: KnowledgeBasePage },
  "/evaluations": { title: "Evaluations", component: EvaluationsPage },
} as const;

function normalizePath(pathname: string) {
  const clean = pathname.replace(/\/+$/, "");
  return clean || "/";
}

function NotFound() {
  return (
    <main className="page not-found">
      <span className="not-found__code">404</span>
      <h1>Trace not found</h1>
      <p>The requested Nexora workspace does not exist.</p>
      <Button variant="primary" onClick={() => navigate("/")}>Return to overview</Button>
    </main>
  );
}

export default function App() {
  const [path, setPath] = useState(() => normalizePath(window.location.pathname));

  useEffect(() => {
    const onNavigation = () => setPath(normalizePath(window.location.pathname));
    window.addEventListener("popstate", onNavigation);
    return () => window.removeEventListener("popstate", onNavigation);
  }, []);

  const route = ROUTES[path as keyof typeof ROUTES];
  const Page = route?.component;
  const title = route?.title ?? "Not found";

  return (
    <AppShell path={path} pageTitle={title}>
      {Page ? <Page /> : <NotFound />}
    </AppShell>
  );
}
