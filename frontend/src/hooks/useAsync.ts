import { useCallback, useEffect, useState } from "react";

export interface AsyncState<T> {
  data: T | undefined;
  loading: boolean;
  error: Error | undefined;
  reload: () => void;
}

/**
 * Minimal data-fetching primitive: run an async fn, track loading/error, and
 * expose a reload. Kept deliberately small — swap in TanStack Query here if the
 * app grows caching/refetch needs (see docs/ARCHITECTURE.md).
 */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [data, setData] = useState<T>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error>();
  const [nonce, setNonce] = useState(0);

  // fn identity is intentionally excluded; callers key on `deps`.
  const run = useCallback(fn, deps); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(undefined);
    run()
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e as Error))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [run, nonce]);

  return { data, loading, error, reload: () => setNonce((n) => n + 1) };
}
