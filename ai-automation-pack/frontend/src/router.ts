export function currentRoute(): string {
  return `${window.location.pathname}${window.location.search}`;
}

export function navigate(path: string, replace = false): void {
  if (currentRoute() === path) return;
  window.history[replace ? "replaceState" : "pushState"]({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function setQueryParam(name: string, value: string | null, replace = false): void {
  setQueryParams({ [name]: value }, replace);
}

export function setQueryParams(values: Record<string, string | null>, replace = false): void {
  const url = new URL(window.location.href);
  for (const [name, value] of Object.entries(values)) {
    if (value) url.searchParams.set(name, value);
    else url.searchParams.delete(name);
  }
  navigate(`${url.pathname}${url.search}`, replace);
}

export function queryParam(name: string): string | null {
  return new URLSearchParams(window.location.search).get(name);
}
