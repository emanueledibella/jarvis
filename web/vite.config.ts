import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
const backend = process.env.JARVIS_DEV_API || "http://127.0.0.1:8765";
if (!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(backend)) throw new Error("Development API proxy must use loopback.");
export default defineConfig({
  base: "./",
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    proxy: {
      "/api": { target: backend, changeOrigin: false },
      "/health": { target: backend, changeOrigin: false },
      "/remote": { target: backend, changeOrigin: false },
      "/oauth": { target: backend, changeOrigin: false },
    },
  },
});
