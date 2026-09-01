/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "mock" (default) | "http" — selects the API adapter. */
  readonly VITE_API?: "mock" | "http";
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
