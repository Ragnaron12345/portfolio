import { useState, type ReactNode } from "react"

import { Icon, type IconName } from "./Icon"

export type PageKey = "overview" | "documents" | "reviews" | "evaluations"

const NAVIGATION: Array<{ key: PageKey; label: string; icon: IconName }> = [
  { key: "overview", label: "Overview", icon: "overview" },
  { key: "documents", label: "Documents", icon: "documents" },
  { key: "reviews", label: "Review queue", icon: "review" },
  { key: "evaluations", label: "Evaluations", icon: "evaluations" },
]

interface AppShellProps {
  page: PageKey
  onNavigate: (page: PageKey) => void
  children: ReactNode
}

export function AppShell({ page, onNavigate, children }: AppShellProps) {
  const [mobileOpen, setMobileOpen] = useState(false)

  const navigate = (nextPage: PageKey) => {
    onNavigate(nextPage)
    setMobileOpen(false)
  }

  return (
    <div className="app-shell">
      <header className="mobile-topbar">
        <button className="icon-button" aria-label="Open navigation" onClick={() => setMobileOpen(true)}>
          <Icon name="menu" />
        </button>
        <span className="mobile-brand">DOCINTEL</span>
      </header>
      {mobileOpen ? <button className="nav-scrim" aria-label="Close navigation" onClick={() => setMobileOpen(false)} /> : null}
      <aside className={`sidebar ${mobileOpen ? "sidebar-open" : ""}`}>
        <div className="brand-block">
          <strong>DOCINTEL</strong>
          <span>DOCUMENT INTELLIGENCE</span>
        </div>
        <nav aria-label="Primary navigation">
          {NAVIGATION.map((item) => (
            <button
              key={item.key}
              className={page === item.key ? "nav-item nav-item-active" : "nav-item"}
              onClick={() => navigate(item.key)}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
        <div className="operator-block">
          <span className="operator-avatar">AR</span>
          <span><strong>Alex Rivera</strong><small>Operations analyst</small></span>
        </div>
      </aside>
      <main className="workspace">{children}</main>
    </div>
  )
}
