import { useCallback, useEffect, useState } from "react";
import { AppShell } from "./components/AppShell";
import { RunDemoModal } from "./components/RunDemoModal";
import { Button } from "./components/Ui";
import { AuditLogPage } from "./pages/AuditLogPage";
import { ExecutionsPage } from "./pages/ExecutionsPage";
import { MockSystemsPage } from "./pages/MockSystemsPage";
import { OverviewPage } from "./pages/OverviewPage";
import { ReviewQueuePage } from "./pages/ReviewQueuePage";
import { currentRoute, navigate } from "./router";

const routeTitles: Record<string, string> = {
  "/": "Workflow operations",
  "/executions": "Executions",
  "/reviews": "Human review",
  "/systems": "Mock systems",
  "/audit": "Audit log",
};

function normalizedPath() {
  const clean = window.location.pathname.replace(/\/+$/, "");
  return clean || "/";
}

function NotFound() {
  return (
    <div className="page not-found">
      <span>404</span><h1>Route not found</h1><p>This Flowline workspace does not exist.</p>
      <Button variant="primary" onClick={() => navigate("/")}>Return to overview</Button>
    </div>
  );
}

export default function App() {
  const [route, setRoute] = useState(currentRoute);
  const [demoOpen, setDemoOpen] = useState(false);
  const path = normalizedPath();
  const openDemo = useCallback(() => setDemoOpen(true), []);
  const closeDemo = useCallback(() => setDemoOpen(false), []);

  useEffect(() => {
    const onNavigation = () => setRoute(currentRoute());
    window.addEventListener("popstate", onNavigation);
    return () => window.removeEventListener("popstate", onNavigation);
  }, []);

  let page;
  if (path === "/") page = <OverviewPage onRunDemo={openDemo} />;
  else if (path === "/executions") page = <ExecutionsPage onRunDemo={openDemo} />;
  else if (path === "/reviews") page = <ReviewQueuePage />;
  else if (path === "/systems") page = <MockSystemsPage />;
  else if (path === "/audit") page = <AuditLogPage />;
  else page = <NotFound />;

  return (
    <AppShell key={route.split("?")[0]} path={path} pageTitle={routeTitles[path] ?? "Not found"} onRunDemo={openDemo}>
      {page}
      <RunDemoModal
        open={demoOpen}
        onClose={closeDemo}
        onCreated={(execution) => {
          closeDemo();
          navigate(`/executions?execution=${encodeURIComponent(execution.execution_id)}`);
        }}
      />
    </AppShell>
  );
}
