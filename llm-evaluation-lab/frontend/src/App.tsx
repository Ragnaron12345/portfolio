import { AppShell } from "./components/AppShell";
import { selectedRunId, useRoute } from "./lib/router";
import { DatasetBrowserPage } from "./pages/DatasetBrowserPage";
import { ExperimentBuilderPage } from "./pages/ExperimentBuilderPage";
import { FailureExplorerPage } from "./pages/FailureExplorerPage";
import { OverviewPage } from "./pages/OverviewPage";
import { PromptRegistryPage } from "./pages/PromptRegistryPage";
import { RagInspectorPage } from "./pages/RagInspectorPage";
import { RunDetailPage } from "./pages/RunDetailPage";

export default function App() {
  const route = useRoute();
  const path = route.split("?")[0];
  let page: React.ReactNode;
  if (path === "/" || path === "/overview") page = <OverviewPage />;
  else if (path === "/experiments/new") page = <ExperimentBuilderPage />;
  else if (path.startsWith("/runs")) page = <RunDetailPage runId={selectedRunId(route)} />;
  else if (path === "/failures") page = <FailureExplorerPage initialRunId={selectedRunId(route)} />;
  else if (path === "/prompts") page = <PromptRegistryPage />;
  else if (path === "/datasets") page = <DatasetBrowserPage />;
  else if (path === "/rag") page = <RagInspectorPage initialRunId={selectedRunId(route)} />;
  else page = <OverviewPage />;
  return <AppShell currentPath={path}>{page}</AppShell>;
}
