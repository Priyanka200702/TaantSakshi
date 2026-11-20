import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { fileURLToPath, URL } from "node:url";

const frontendRoot = fileURLToPath(new URL(".", import.meta.url));
const staticOutput = fileURLToPath(new URL("../backend/static", import.meta.url));

export default defineConfig({
  root: frontendRoot,
  base: "/static/",
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  define: {
    "process.env.REACT_APP_BACKEND_URL": JSON.stringify(
      process.env.REACT_APP_BACKEND_URL || "",
    ),
  },
  server: {
    host: "127.0.0.1",
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: staticOutput,
    emptyOutDir: false,
    rollupOptions: {
      input: fileURLToPath(new URL("./app.html", import.meta.url)),
      output: {
        entryFileNames: "assets/[name]-[hash].js",
        chunkFileNames: "assets/[name]-[hash].js",
        assetFileNames: "assets/[name]-[hash][extname]",
      },
    },
  },
});
