import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
  build: {
    rollupOptions: {
      // Two documents from one project: the existing site keeps `index.html`,
      // and the refreshed CourseMate shell is served from `ui.html` at `/app`.
      input: {
        main: "index.html",
        ui: "ui.html",
      },
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    restoreMocks: true,
    setupFiles: ["./src/test/setup.ts"],
    testTimeout: 15_000,
  },
});
