/**
 * Сквозной trace_id (32 hex, uuid4 без дефисов): фронт генерирует его на каждый
 * запрос к hub и шлёт X-Trace-Id; hub → раннер → Langfuse/LangSmith/БД несут тот
 * же id. Здесь — генератор и «последний trace» для статус-бара.
 */
import { useSyncExternalStore } from "react";

export const TRACE_HEADER = "X-Trace-Id";

export function newTraceId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID().replaceAll("-", "");
  /* non-secure context fallback */
  return Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join("");
}

/** «trace …abcd» — короткая метка для UI. */
export const traceTail = (id: string) => `trace …${id.slice(-4)}`;

export interface LastTrace {
  id: string;
  /** "POST /repositories/1/trigger" */
  action: string;
  ok: boolean | null; // null — in flight
}

let last: LastTrace | null = null;
const listeners = new Set<() => void>();

export function setLastTrace(t: LastTrace): void {
  last = t;
  listeners.forEach((l) => l());
}

export function useLastTrace(): LastTrace | null {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => last,
  );
}
