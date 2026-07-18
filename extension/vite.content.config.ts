import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const projectRoot = dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  build: {
    outDir: "dist",
    emptyOutDir: false,
    rollupOptions: {
      input: resolve(projectRoot, "src/content.ts"),
      output: {
        format: "iife",
        entryFileNames: "assets/content.js",
        inlineDynamicImports: true,
      },
    },
  },
});
