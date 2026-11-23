import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// path ที่ส่งต่อไปยัง Search API (production: Caddy ส่งต่อ path เดียวกันนี้)
// route ฝั่งเว็บต้องไม่ขึ้นต้นด้วย path เหล่านี้
const API_PREFIXES = ["/auth", "/search", "/sightings", "/journeys", "/cameras"];

export default defineConfig(({ mode }) => {
  // เปลี่ยนปลายทาง API ตอน dev ได้ด้วย FLOCK_API_TARGET (ค่าเริ่ม http://127.0.0.1:8000)
  const apiTarget = loadEnv(mode, ".", "FLOCK_").FLOCK_API_TARGET || "http://127.0.0.1:8000";
  return {
    plugins: [react()],
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
      proxy: Object.fromEntries(API_PREFIXES.map((p) => [p, { target: apiTarget, changeOrigin: false }])),
    },
    build: {
      sourcemap: false,
    },
    test: {
      environment: "node",
      include: ["src/**/*.test.ts"],
    },
  };
});
