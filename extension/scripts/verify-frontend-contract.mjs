import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const files = [
  "src/api/crawler_client.ts",
  "src/api/paths.ts",
  "src/api/types.ts",
  "src/config.ts",
  "src/analysis_view_model.ts",
  "src/sidepanel.ts",
  "src/collection_flow.ts",
];

const content = Object.fromEntries(files.map((file) => [file, readFileSync(resolve(root, file), "utf8")]));

const requiredCrawlerMethods = [
  "getAuthStatus",
  "startLogin",
  "getLoginJob",
  "startCollection",
  "getCollectionJob",
  "getCollectionResult",
];

for (const method of requiredCrawlerMethods) {
  if (!content["src/api/crawler_client.ts"].includes(method)) {
    throw new Error(`Missing crawler API method: ${method}`);
  }
}

for (const phrase of ["跨平台", "多平台", "平台对比", "B站", "bilibili", "淘宝评论"]) {
  for (const [file, source] of Object.entries(content)) {
    if (source.includes(phrase)) {
      throw new Error(`Forbidden phrase "${phrase}" found in ${file}`);
    }
  }
}

if (!content["src/analysis_view_model.ts"].includes("normalizeAnalysisResult")) {
  throw new Error("normalizeAnalysisResult is missing");
}

if (!content["src/config.ts"]?.includes("VITE_USE_MOCK")) {
  throw new Error("Mock/real mode config is missing");
}

console.log("verify-frontend-contract: ok");
