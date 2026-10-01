import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "node:path";

// This browser-only entry must never be reachable in a normal Vite build or
// pointed at the developer's ordinary API / production backend.
if (process.env.WANASAH_P19_REAL_BROWSER_CONFIRM !== "DISPOSABLE_PG16_ONLY") {
  throw new Error("Real-browser acceptance requires disposable-only authorization.");
}

export default defineConfig({
  plugins: [react()],
  define: {
    "import.meta.env.VITE_P19_REAL_BROWSER": JSON.stringify("isolated-only"),
    "import.meta.env.VITE_API_URL": JSON.stringify("http://127.0.0.1:5188/acceptance-real"),
    "import.meta.env.VITE_SENTRY_DSN": JSON.stringify(""),
  },
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: {
    host: "127.0.0.1", port: 5188, strictPort: true,
    headers: {
      "Content-Security-Policy": "connect-src 'self' ws://127.0.0.1:5188; form-action 'self'",
    },
    proxy: {
      "/acceptance-real": {
        target: "http://127.0.0.1:18046",
        changeOrigin: false,
        ws: true,
        rewrite: (url) => url.replace(/^\/acceptance-real/, ""),
      },
    },
  },
});
