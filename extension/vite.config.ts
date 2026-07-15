import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";

const projectRoot = dirname(fileURLToPath(import.meta.url));

function emitManifest(): Plugin {
  return {
    name: "emit-extension-manifest",
    generateBundle() {
      this.emitFile({
        type: "asset",
        fileName: "manifest.json",
        source: readFileSync(resolve(projectRoot, "manifest.json"), "utf8"),
      });
    },
  };
}

export default defineConfig({
  plugins: [emitManifest()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        sidepanel: resolve(projectRoot, "sidepanel.html"),
        background: resolve(projectRoot, "src/background.ts"),
        content: resolve(projectRoot, "src/content.ts"),
      },
      output: {
        entryFileNames: "assets/[name].js",
        chunkFileNames: "assets/[name]-[hash].js",
        assetFileNames: "assets/[name]-[hash][extname]",
      },
    },
  },
});
