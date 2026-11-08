// `defineConfig` comes from `vitest/config`, not from `vite`.
// Taking it from `vite` leaves the `test` key off the type, so `tsc --noEmit`
// is the only thing that fails: tests and builds both still pass.
// Measured on 2026-09-02, recorded in the MVP specification section 2.2.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    // Loopback only. The MVP has no authentication, so nothing here is meant
    // to be reachable from the LAN.
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    // The client calls the backend by path alone (`/api/...`), so during
    // development the screen and the API must look like one origin. This
    // forwards /api to the backend; the browser never talks to port 8000.
    // Development only: `server` is not part of the build, and a deployment
    // puts its own entrance in front instead (ADR 0002, issue 1).
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
    // CSS is left unprocessed on purpose. CSS Modules arrive as a proxy, so a
    // component test can render without any styling setup. Class names are
    // not what these tests assert on: they query by role and text.
    css: false,
  },
});
