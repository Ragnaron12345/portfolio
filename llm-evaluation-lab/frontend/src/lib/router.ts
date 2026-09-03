import { useEffect, useState } from "react";

const NAVIGATE_EVENT = "evalforge:navigate";

export function navigate(path: string, replace = false): void {
  window.history[replace ? "replaceState" : "pushState"]({}, "", path);
  window.dispatchEvent(new Event(NAVIGATE_EVENT));
}

export function useRoute(): string {
  const read = () => `${window.location.pathname}${window.location.search}`;
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const update = () => setRoute(read());
    window.addEventListener("popstate", update);
    window.addEventListener(NAVIGATE_EVENT, update);
    return () => {
      window.removeEventListener("popstate", update);
      window.removeEventListener(NAVIGATE_EVENT, update);
    };
  }, []);
  return route;
}

export function selectedRunId(route: string): string | null {
  const pathMatch = route.match(/^\/runs\/([^?]+)/);
  if (pathMatch) return decodeURIComponent(pathMatch[1]);
  const query = route.includes("?") ? route.slice(route.indexOf("?")) : "";
  return new URLSearchParams(query).get("runId");
}
