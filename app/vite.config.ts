import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";
import { readFileSync } from "node:fs";

const pkg = JSON.parse(readFileSync(path.resolve(__dirname, "package.json"), "utf8"));

const host = process.env.TAURI_DEV_HOST;

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: { "import.meta.env.VITE_APP_VERSION": JSON.stringify(pkg.version) },
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host ? { protocol: "ws", host, port: 1421 } : undefined,
    watch: { ignored: ["**/src-tauri/**"] },
  },
  build: {
    target: "es2022",
    chunkSizeWarningLimit: 6000,
    // 0.9.1: stable vendor chunks stay cached across app updates
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (!id.includes("node_modules")) return undefined;
          if (/[\\/](react|react-dom|scheduler)[\\/]/.test(id)) return "react";
          if (id.includes("@radix-ui") || id.includes("react-resizable-panels")) return "ui";
          if (id.includes("lucide-react")) return "icons";
          if (id.includes("@tauri-apps")) return "tauri";
          return undefined;
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
