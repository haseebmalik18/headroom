/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Served from https://haseebmalik18.github.io/hotpath/
export default defineConfig({
  base: "/hotpath/",
  plugins: [react()],
  test: { include: ["src/**/*.test.ts"] },
});
