import { defineConfig } from "vite";
import { resolve } from "node:path";

export default defineConfig({
  root: resolve(__dirname, "web"),
  build: {
    outDir: resolve(__dirname, "web/dist"),
    emptyDir: true,
    sourcemap: true,
    rollupOptions: {
      input: resolve(__dirname, "web/index.html"),
    },
  },
});
