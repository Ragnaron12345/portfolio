import { useCallback, useEffect, useRef, useState } from "react";

export interface PollingResource<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  refreshing: boolean;
  lastUpdated: Date | null;
  reload: () => void;
}

export function usePollingResource<T>(
  load: (signal: AbortSignal) => Promise<T>,
  dependencies: readonly unknown[],
  intervalMs = 5_000,
): PollingResource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const loaderRef = useRef(load);
  loaderRef.current = load;

  const reload = useCallback(() => setReloadToken((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    let hasLoaded = false;

    const run = async () => {
      if (hasLoaded) setRefreshing(true);
      else setLoading(true);
      try {
        const result = await loaderRef.current(controller.signal);
        if (!active) return;
        setData(result);
        setError(null);
        setLastUpdated(new Date());
        hasLoaded = true;
      } catch (candidate) {
        if (!active || controller.signal.aborted) return;
        setError(candidate instanceof Error ? candidate : new Error("The service returned an unexpected error."));
      } finally {
        if (active) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    };

    void run();
    const timer = intervalMs > 0 ? window.setInterval(() => void run(), intervalMs) : undefined;
    return () => {
      active = false;
      controller.abort();
      if (timer !== undefined) window.clearInterval(timer);
    };
    // The caller provides primitive dependencies to intentionally restart polling.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...dependencies, intervalMs, reloadToken]);

  return { data, error, loading, refreshing, lastUpdated, reload };
}
