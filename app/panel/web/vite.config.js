// Сборка интерфейса панели; dist/ раздаёт сервер панели (не в Git).
// npm run dev — разработка с прокси API на работающую панель.
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

const panel = process.env.PANEL_URL || "http://127.0.0.1:8090";

export default defineConfig({
  plugins: [vue()],
  base: "./",
  build: { outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 900 },
  server: { proxy: { "/api": { target: panel, changeOrigin: true } } },
});
