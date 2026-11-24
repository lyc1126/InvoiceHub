import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";

// The build output is committed under web/static/app so release packaging keeps
// shipping web/ unchanged. Stable file names keep FILE_MAP and the packaging
// allowlists fixed; the project-wide ?v= rule (web/static immutable caching)
// busts caches with a content hash instead of hashed names.
function versionQuery(): Plugin {
  return {
    name: "invoicehub-version-query",
    enforce: "post",
    generateBundle(_options, bundle) {
      const html = bundle["index.html"];
      if (!html || html.type !== "asset") return;
      let text = String(html.source);
      for (const item of Object.values(bundle)) {
        if (item.fileName === "index.html") continue;
        const content = item.type === "chunk" ? item.code : item.source;
        const version = createHash("sha256").update(content).digest("hex").slice(0, 12);
        text = text.replaceAll(`/static/app/${item.fileName}"`, `/static/app/${item.fileName}?v=${version}"`);
      }
      html.source = text;
    },
  };
}

export default defineConfig({
  base: "/static/app/",
  plugins: [vue(), versionQuery()],
  build: {
    outDir: fileURLToPath(new URL("../web/static/app", import.meta.url)),
    emptyOutDir: true,
    sourcemap: false,
    rolldownOptions: {
      output: {
        codeSplitting: false,
        entryFileNames: "assets/app.js",
        assetFileNames: "assets/app[extname]",
      },
    },
  },
  server: {
    // `pnpm dev` proxies API calls to a locally running InvoiceHub backend.
    proxy: { "/api": "http://127.0.0.1:8766" },
  },
  test: {
    environment: "happy-dom",
    include: ["tests/**/*.spec.ts"],
  },
});
