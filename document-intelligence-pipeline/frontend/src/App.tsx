import { useEffect, useState } from "react"

import { AppShell, type PageKey } from "./components/AppShell"
import { DocumentsPage } from "./pages/DocumentsPage"
import { EvaluationsPage } from "./pages/EvaluationsPage"
import { OverviewPage } from "./pages/OverviewPage"
import { ReviewQueuePage } from "./pages/ReviewQueuePage"

function pageFromHash(): PageKey {
  const value = window.location.hash.replace("#", "")
  return ["overview", "documents", "reviews", "evaluations"].includes(value) ? value as PageKey : "overview"
}

export function App() {
  const [page, setPage] = useState<PageKey>(() => pageFromHash())

  useEffect(() => {
    const onHashChange = () => setPage(pageFromHash())
    window.addEventListener("hashchange", onHashChange)
    return () => window.removeEventListener("hashchange", onHashChange)
  }, [])

  const navigate = (nextPage: PageKey) => {
    window.location.hash = nextPage
    setPage(nextPage)
  }

  return (
    <AppShell page={page} onNavigate={navigate}>
      {page === "overview" ? <OverviewPage onNavigate={navigate} /> : null}
      {page === "documents" ? <DocumentsPage onOpenReview={() => navigate("reviews")} /> : null}
      {page === "reviews" ? <ReviewQueuePage /> : null}
      {page === "evaluations" ? <EvaluationsPage /> : null}
    </AppShell>
  )
}
