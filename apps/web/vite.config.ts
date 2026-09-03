import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // WSL2: the dev server runs in Linux and the browser is on Windows, so
    // binding to localhost only makes it unreachable. `npm run dev` also
    // passes --host 0.0.0.0; this keeps it true however vite is started.
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      // One origin in the browser, so no CORS config and no base URL to
      // get wrong between dev and preview.
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
