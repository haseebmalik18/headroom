/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Served from https://haseebmalik18.github.io/hotpath/. In development, /api goes to `hotpath serve`.
export default defineConfig({
  base: "/hotpath/",
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
  test: { include: ["src/**/*.test.ts"] },
});
