import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { CourseMateUi } from "./CourseMateUi";

declare global {
  interface Window {
    COURSEMATE_CONFIG?: { apiBase: string };
  }
}

/**
 * Entry point for the new CourseMate single-page application.
 *
 * `apps/web/ui.html` loads this module and is served at `/app`, so the new shell
 * and the existing site keep separate documents and cannot fight over global CSS.
 */
const apiBase = import.meta.env.VITE_UI_API_BASE ?? "/ui-extension/api/ui/v1";
window.COURSEMATE_CONFIG = { apiBase };

const container = document.getElementById("root");
if (container === null) {
  throw new Error("CourseMate root element was not found.");
}

createRoot(container).render(
  <StrictMode>
    <CourseMateUi />
  </StrictMode>,
);
