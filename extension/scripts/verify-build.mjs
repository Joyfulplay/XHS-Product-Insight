import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const distRoot = resolve(projectRoot, "dist");
const manifestPath = resolve(distRoot, "manifest.json");
const contentPath = resolve(distRoot, "assets/content.js");
const requiredMatches = [
  "https://item.taobao.com/*",
  "https://detail.tmall.com/*",
  "https://chaoshi.detail.tmall.com/*",
  "https://detail.m.tmall.com/*",
  "https://detail.tmall.hk/*",
];

function fail(message) {
  console.error(`verify-build: ${message}`);
  process.exitCode = 1;
}

if (!existsSync(manifestPath)) {
  fail("dist/manifest.json does not exist");
}

if (!existsSync(contentPath)) {
  fail("dist/assets/content.js does not exist");
}

if (existsSync(contentPath)) {
  const content = readFileSync(contentPath, "utf8");
  const topLevelModuleSyntax = /^[ \t]*(?:import|export)[ \t]/m;
  if (topLevelModuleSyntax.test(content)) {
    fail("content.js contains top-level import/export syntax");
  }
  if (content.includes("product_page-")) {
    fail("content.js still references an external product_page chunk");
  }
}

if (existsSync(manifestPath)) {
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  const contentScript = manifest.content_scripts?.[0];
  const contentJs = contentScript?.js?.[0];
  const backgroundJs = manifest.background?.service_worker;
  const sidePanelPath = manifest.side_panel?.default_path;

  for (const filePath of [contentJs, backgroundJs, sidePanelPath]) {
    if (!filePath) {
      fail("manifest is missing a required extension file reference");
      continue;
    }
    if (!existsSync(resolve(distRoot, filePath))) {
      fail(`manifest references missing file: ${filePath}`);
    }
  }

  for (const match of requiredMatches) {
    if (!contentScript?.matches?.includes(match)) {
      fail(`manifest content_scripts.matches is missing ${match}`);
    }
  }
}

if (process.exitCode) {
  process.exit();
}

console.log("verify-build: ok");
