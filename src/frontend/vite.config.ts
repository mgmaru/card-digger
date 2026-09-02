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
    // to be reachable from the LAN. `card_digger.api.main` allows exactly
    // this origin, and 127.0.0.1 on the same port, through CORS.
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
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
