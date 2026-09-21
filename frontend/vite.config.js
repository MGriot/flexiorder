import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Backend started with `python run.py` (default port 8765).
const backend = process.env.FLEXIORDER_PORT || "8765";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": `http://127.0.0.1:${backend}`,
      "/ws": { target: `ws://127.0.0.1:${backend}`, ws: true },
    },
  },
  build: {
    outDir: "../backend/static",
    emptyOutDir: true,
  },
});
