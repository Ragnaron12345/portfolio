import { useEffect, useRef, useState, type ReactNode } from "react";
import { client } from "../api/client";
import { usePollingResource } from "../hooks/usePollingResource";
import { navigate } from "../router";
import { Icon, type IconName } from "./Icon";

export const NAV_ITEMS: Array<{ path: string; label: string; shortLabel: string; icon: IconName }> = [
  { path: "/", label: "Overview", shortLabel: "Overview", icon: "overview" },
  { path: "/executions", label: "Executions", shortLabel: "Executions", icon: "executions" },
  { path: "/reviews", label: "Review Queue", shortLabel: "Reviews", icon: "reviews" },
  { path: "/systems", label: "Mock Systems", shortLabel: "Systems", icon: "systems" },
  { path: "/audit", label: "Audit Log", shortLabel: "Audit", icon: "audit" },
];

function Brand() {
  return (
    <a className="brand" href="/" onClick={(event) => { event.preventDefault(); navigate("/"); }} aria-label="Flowline home">
      <svg className="brand__mark" viewBox="0 0 32 32" aria-hidden="true">
        <path d="M16 2 28 9v14l-12 7L4 23V9Z" />
        <path d="m11 10 5-3 5 3-5 3-5-3Zm0 0v8l5 3 5-3v-4m-10 4-4 2.5m14-2.5 4 2.5" />
      </svg>
      <span><strong>FLOWLINE</strong><small>AI Automation Pack</small></span>
    </a>
  );
}

function useUtcClock() {
  const [clock, setClock] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setClock(new Date()), 1_000);
    return () => window.clearInterval(timer);
  }, []);
  return clock.toLocaleTimeString("en-GB", { hour12: false, timeZone: "UTC" });
}

export function AppShell({
  path,
  pageTitle,
  onRunDemo,
  children,
}: {
  path: string;
  pageTitle: string;
  onRunDemo: () => void;
  children: ReactNode;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const sidebarRef = useRef<HTMLElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const clock = useUtcClock();
  const health = usePollingResource(() => client.getHealth(), [], 15_000);
  const healthTone = health.data?.status === "healthy" || health.data?.status === "ok" ? "healthy" : health.error ? "unhealthy" : "degraded";
  const healthLabel = health.data?.label ?? (health.error ? "API unavailable" : "Checking systems");

  useEffect(() => {
    document.title = `${pageTitle} · Flowline`;
    setMobileOpen(false);
  }, [pageTitle, path]);

  useEffect(() => {
    if (!mobileOpen) return;
    const focusable = () => Array.from(sidebarRef.current?.querySelectorAll<HTMLElement>("a[href], button:not([disabled])") ?? []);
    window.requestAnimationFrame(() => focusable()[0]?.focus());
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMobileOpen(false);
        window.requestAnimationFrame(() => menuButtonRef.current?.focus());
      }
      if (event.key !== "Tab") return;
      const controls = focusable();
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [mobileOpen]);

  const activePath = path === "/" ? "/" : `/${path.split("/").filter(Boolean)[0] ?? ""}`;

  return (
    <div className="app-shell">
      <aside ref={sidebarRef} className={`sidebar${mobileOpen ? " sidebar--open" : ""}`} aria-label="Primary navigation">
        <div className="sidebar__brand-row">
          <Brand />
          <button className="icon-button sidebar__close" onClick={() => setMobileOpen(false)} aria-label="Close navigation"><Icon name="close" /></button>
        </div>
        <nav className="sidebar__nav">
          {NAV_ITEMS.map((item) => {
            const active = activePath === item.path;
            return (
              <a
                className={`nav-item${active ? " nav-item--active" : ""}`}
                href={item.path}
                key={item.path}
                aria-current={active ? "page" : undefined}
                onClick={(event) => { event.preventDefault(); navigate(item.path); }}
              >
                <Icon name={item.icon} /><span>{item.label}</span>
              </a>
            );
          })}
        </nav>
        <div className="sidebar__spacer" />
        <div className="sidebar__operator">
          <span className="operator-avatar">OP</span>
          <span><strong>Ops Operator</strong><small>operator@flowline.io</small></span>
          <Icon name="chevron" />
        </div>
      </aside>
      {mobileOpen ? <button className="nav-scrim" aria-label="Close navigation" onClick={() => setMobileOpen(false)} /> : null}

      <div className="workspace">
        <header className="global-topbar">
          <button ref={menuButtonRef} className="icon-button global-topbar__menu" onClick={() => setMobileOpen(true)} aria-label="Open navigation"><Icon name="menu" /></button>
          <div className="global-topbar__brand"><Brand /></div>
          <div className={`health-state health-state--${healthTone}`} title={healthLabel}><span />{healthLabel}</div>
          <div className="global-topbar__tools">
            <time dateTime={new Date().toISOString()}>{clock} UTC</time>
            <button className="button button--primary run-demo-button" onClick={onRunDemo}><Icon name="play" /> Run demo</button>
          </div>
        </header>
        <main className="main-content" id="main-content">{children}</main>
        <nav className="mobile-nav" aria-label="Mobile navigation">
          {NAV_ITEMS.map((item) => {
            const active = activePath === item.path;
            return (
              <a
                key={item.path}
                className={active ? "mobile-nav__item mobile-nav__item--active" : "mobile-nav__item"}
                href={item.path}
                aria-current={active ? "page" : undefined}
                onClick={(event) => { event.preventDefault(); navigate(item.path); }}
              ><Icon name={item.icon} /><span>{item.shortLabel}</span></a>
            );
          })}
        </nav>
      </div>
    </div>
  );
}
