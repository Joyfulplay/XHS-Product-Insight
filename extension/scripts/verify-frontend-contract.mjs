import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import ts from "typescript";

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

for (const requiredSnippet of [
  'authStatus: (refresh = false)',
  'startLogin("auto", true',
  'getAuthStatus({ refresh: true }',
  'max_notes: config?.max_notes ?? 10',
  'max_comments_per_note: config?.max_comments_per_note ?? 20',
  'this.startCollection(request.page_product, request.keyword, request.config, signal)',
]) {
  if (!Object.values(content).some((source) => source.includes(requiredSnippet))) {
    throw new Error(`Missing real-login contract: ${requiredSnippet}`);
  }
}

for (const requiredSnippet of [
  'chrome.tabs.create({ url })',
  'safeExternalUrl(value)',
  '"source_url", "url", "note_url", "link"',
  '`https://www.xiaohongshu.com/explore/${encodeURIComponent(noteId)}`',
  'PRODUCT_CACHE_KEY_PREFIX = "trustlens.productResult."',
  'PRODUCT_CACHE_INDEX_KEY = "trustlens.productResultIndex"',
  'MAX_PRODUCT_CACHE_ENTRIES = 10',
  'function productKeyFor(product',
  'function saveProductResult(',
  'function loadProductResult(',
  'function applyStoredProductResult(',
  'rawCollectionResult',
  'analysisResult',
  'noteCount',
  'commentCount',
  'completedAt',
  'savedAt',
  'state.view = "restoring"',
  'await loadProductResult(nextProductKey)',
  'applyStoredProductResult(cached)',
  'await restoreActiveCollectionTask()',
  'await checkCrawlerService()',
  'applyAuthStatus(authStatus)',
  'isTemporaryAuthCheckError(error)',
  '采集服务认证检查暂时失败，历史结果已保留。',
  'await pollCollectionJob(storedTask.jobId',
  'fetchedCompletedResults.has(jobId)',
  'await crawlerClient.startCrawl(startRequest',
]) {
  if (!Object.values(content).some((source) => source.includes(requiredSnippet))) {
    throw new Error(`Missing persistence/original-link contract: ${requiredSnippet}`);
  }
}

if (Object.values(content).some((source) => source.includes("chrome.storage.local.clear") || source.includes(".clear()"))) {
  throw new Error("Forbidden storage clear call found; extension must only remove its own expired keys");
}

const sidepanel = content["src/sidepanel.ts"];
const initializeBody = sidepanel.slice(sidepanel.indexOf("async function initialize()"));
if (initializeBody.indexOf('await loadProductResult(nextProductKey)') > initializeBody.indexOf('await checkCrawlerService()')) {
  throw new Error("Initialization order must restore product cache before auth status check");
}
if (sidepanel.includes("state.collectionResult = null;\n  state.collection.starting = false")) {
  throw new Error("Resetting task controls must not clear historical collectionResult");
}
if (!sidepanel.includes('storageRemove(expiredKeys)')) {
  throw new Error("LRU pruning must remove only expired TrustLens product-result keys");
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

const analysisViewModelJs = ts.transpileModule(content["src/analysis_view_model.ts"], {
  compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022, verbatimModuleSyntax: true },
}).outputText;
const { normalizeAnalysisResult } = await import(`data:text/javascript,${encodeURIComponent(analysisViewModelJs)}`);
const schema11Result = {
  schema_version: "1.1",
  collection: {
    candidate_count: 50,
    note_count: 10,
    comment_count: 53,
    valid_comment_count: 41,
  },
  llm_insights: {
    overall_summary: "正式 LLM 总结",
    product_attributes: ["降噪", "音质"],
    usage_scenarios: ["通勤"],
    user_types: ["通勤用户"],
    unsuitable_users: ["预算敏感用户"],
    pros: ["降噪稳定"],
    cons: ["价格较高"],
    purchase_advice: "适合重视降噪的用户。",
  },
  statistics: {
    keywords: [{ text: "降噪", count: 12, weight: 1 }],
    sentiment_distribution: { positive: 0.6, neutral: 0.3, negative: 0.1 },
    risk_ratio: 0.2,
  },
  representative_notes: [{ note_id: "note-1", title: "真实体验", url: "https://www.xiaohongshu.com/explore/note-1", score: 0.9, summary: "代表笔记" }],
  notes: Array.from({ length: 10 }, (_, index) => ({
    id: `note-${index}`,
    comments: Array.from({ length: index === 0 ? 8 : 5 }, (__, commentIndex) => ({ id: `comment-${index}-${commentIndex}` })),
  })),
};
const normalizedSchema11 = normalizeAnalysisResult(schema11Result);
if (normalizedSchema11.sample.note_count !== 10) {
  throw new Error(`schema 1.1 note_count mapping failed: expected 10, got ${normalizedSchema11.sample.note_count}`);
}
if (normalizedSchema11.sample.raw_comment_count !== 53) {
  throw new Error(`schema 1.1 comment_count mapping failed: expected 53, got ${normalizedSchema11.sample.raw_comment_count}`);
}
if (schema11Result.notes.length !== 10) {
  throw new Error("schema 1.1 fixture notes.length should be 10");
}
if (normalizedSchema11.sample.valid_comment_count !== 41) {
  throw new Error(`schema 1.1 valid_comment_count mapping failed: expected 41, got ${normalizedSchema11.sample.valid_comment_count}`);
}
if (normalizedSchema11.sample.risk_negative_ratio !== 0.2) {
  throw new Error(`schema 1.1 risk_ratio mapping failed: expected 0.2, got ${normalizedSchema11.sample.risk_negative_ratio}`);
}
if (normalizedSchema11.keywords[0] !== "降噪") {
  throw new Error("schema 1.1 statistics.keywords mapping failed");
}
if (normalizedSchema11.evidence[0]?.source_url !== "https://www.xiaohongshu.com/explore/note-1") {
  throw new Error("schema 1.1 representative_notes mapping failed");
}
const linkOnlyResult = { representative_notes: [{ note_id: "generated-note", title: "无 URL 笔记" }, { title: "link 笔记", link: "https://www.xiaohongshu.com/explore/link-note" }] };
const normalizedLinkOnly = normalizeAnalysisResult(linkOnlyResult);
if (normalizedLinkOnly.evidence[0]?.source_url !== "https://www.xiaohongshu.com/explore/generated-note") {
  throw new Error("note_id fallback URL mapping failed");
}
if (normalizedLinkOnly.evidence[1]?.source_url !== "https://www.xiaohongshu.com/explore/link-note") {
  throw new Error("link source URL mapping failed");
}

console.log("verify-frontend-contract: ok");
