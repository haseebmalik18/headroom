/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Served from https://haseebmalik18.github.io/headroom/. In development, /api goes to `headroom serve`.
export default defineConfig({
  base: "/headroom/",
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
  test: { include: ["src/**/*.test.ts"] },
});
