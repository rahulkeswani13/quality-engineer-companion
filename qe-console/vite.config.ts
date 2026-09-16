import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/threads": "http://127.0.0.1:8000",
      "/holds": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
      "/scenarios": "http://127.0.0.1:8000",
      "/demo": "http://127.0.0.1:8000",
      "/auth": "http://127.0.0.1:8000",
    },
  },
});
