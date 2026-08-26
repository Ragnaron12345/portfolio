import { useEffect, useRef, useState, type ReactNode } from "react";
import { Icon, type IconName } from "./Icon";

export interface NavItem {
  path: string;
  label: string;
  icon: IconName;
}

export const NAV_ITEMS: NavItem[] = [
  { path: "/", label: "Overview", icon: "overview" },
  { path: "/console", label: "Request Console", icon: "console" },
  { path: "/reviews", label: "Review Queue", icon: "reviews" },
  { path: "/knowledge", label: "Knowledge Base", icon: "knowledge" },
  { path: "/evaluations", label: "Evaluations", icon: "evaluations" },
];

function Brand() {
  return (
    <div className="brand" aria-label="Nexora AI Operations">
      <span className="brand__word">NE<span>X</span>ORA</span>
      <span className="brand__descriptor">AI Operations</span>
    </div>
  );
}

export function navigate(path: string) {
  if (window.location.pathname === path) return;
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function AppShell({
  path,
  pageTitle,
  children,
}: {
  path: string;
  pageTitle: string;
  children: ReactNode;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [mobileViewport, setMobileViewport] = useState(false);
  const sidebarRef = useRef<HTMLElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  function closeMobileNavigation(restoreFocus = true) {
    setMobileOpen(false);
    if (restoreFocus) window.requestAnimationFrame(() => menuButtonRef.current?.focus());
  }

  useEffect(() => {
    setMobileOpen(false);
    document.title = `${pageTitle} · Nexora`;
  }, [path, pageTitle]);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(max-width: 1040px)");
    const update = () => setMobileViewport(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    if (!mobileOpen) return;
    const focusable = () => Array.from(
      sidebarRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]), a[href]') ?? [],
    );
    window.requestAnimationFrame(() => focusable()[0]?.focus());
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeMobileNavigation();
        return;
      }
      if (event.key !== "Tab") return;
      const controls = focusable();
      if (!controls.length) return;
      const first = controls[0]!;
      const last = controls[controls.length - 1]!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mobileOpen]);

  const navigationHidden = mobileViewport && !mobileOpen;

  return (
    <div className="app-shell">
      <aside
        ref={sidebarRef}
        id="primary-navigation"
        className={`sidebar${mobileOpen ? " sidebar--open" : ""}`}
        aria-label="Primary navigation"
        aria-hidden={navigationHidden || undefined}
        inert={navigationHidden}
      >
        <div className="sidebar__top">
          <Brand />
          <button className="icon-button sidebar__close" onClick={() => closeMobileNavigation()} aria-label="Close navigation">
            <Icon name="close" />
          </button>
        </div>
        <nav className="sidebar__nav">
          {NAV_ITEMS.map((item) => {
            const active = path === item.path;
            return (
              <a
                key={item.path}
                href={item.path}
                className={`nav-item${active ? " nav-item--active" : ""}`}
                aria-current={active ? "page" : undefined}
                onClick={(event) => {
                  event.preventDefault();
                  navigate(item.path);
                }}
              >
                <Icon name={item.icon} />
                <span>{item.label}</span>
              </a>
            );
          })}
        </nav>
        <div className="sidebar__footer">
          <div className="operator-avatar">OP</div>
          <div>
            <strong>ops_admin</strong>
            <span>Platform operator</span>
          </div>
          <span className="system-dot system-dot--session" aria-label="Local operator session" title="Local operator session" />
        </div>
      </aside>
      {mobileOpen ? <button className="nav-scrim" aria-label="Close navigation" onClick={() => closeMobileNavigation()} /> : null}
      <div className="workspace">
        <header className="mobile-topbar">
          <Brand />
          <span className="mobile-topbar__title">{pageTitle}</span>
          <button
            ref={menuButtonRef}
            className="icon-button"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
            aria-controls="primary-navigation"
            aria-expanded={mobileOpen}
          >
            <Icon name="menu" />
          </button>
        </header>
        {children}
      </div>
    </div>
  );
}
