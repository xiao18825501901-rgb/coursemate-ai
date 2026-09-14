/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_AGENT_API_URL?: string;
  readonly VITE_AUTH_TEST_TOKEN?: string;
  readonly VITE_CLERK_PUBLISHABLE_KEY?: string;
  readonly VITE_RAG_API_URL?: string;
  readonly VITE_UI_API_BASE?: string;
  readonly VITE_V3_ENABLED?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
