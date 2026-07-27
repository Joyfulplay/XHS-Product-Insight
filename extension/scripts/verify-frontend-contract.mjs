import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const files = [
  "src/api/crawler_client.ts",
  "src/api/paths.ts",
  "src/api/types.ts",
  "src/config.ts",
  "src/analysis_view_model.ts",
  "src/source_link.ts",
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
  "analyzeCollection",
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
  "link_expires_at",
  "data-source-expires-at",
  "sourceLinkProblem",
  "原文链接已过期，请重新采集。",
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
const sourceLinkJs = ts.transpileModule(content["src/source_link.ts"], {
  compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022, verbatimModuleSyntax: true },
}).outputText;
const { sourceLinkProblem } = await import(`data:text/javascript,${encodeURIComponent(sourceLinkJs)}`);
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
    pros: ["旧版优点字段"],
    cons: ["旧版缺点字段"],
    purchase_advice: "适合重视降噪的用户。",
  },
  pros: ["降噪表现稳定。", "佩戴体验舒适。", "续航满足日常使用。"],
  cons: ["产品价格较高。", "长时间佩戴可能闷热。", "部分场景证据不足。"],
  purchase_reference: {
    trust_aware_one_liner: "可信结论",
    raw_one_liner: "原始结论",
    recommended_default_mode: "trust_aware",
    reasons_for_difference: ["高风险内容被降权"],
    evidence_ids: ["e1"],
  },
  sample_overview: {
    posts_analyzed: 10,
    comment_count: 53,
    coverage_note: "样本仅覆盖小红书。",
  },
  sentiment_scores: {
    raw: 82,
    trust_aware: 76,
    analysis_confidence: 88,
    score_disclaimer: "分数反映评价情感倾向，不是商品客观质量分。",
  },
  risk_overview: {
    high_risk_content_count: 3,
    high_risk_content_ratio: 0.3,
    reason_distribution: [{ reason: "营销式表达", count: 3 }],
    caution: "风险分数表示内容需要谨慎参考，不代表评论一定虚假。",
  },
  platform: {
    name: "xiaohongshu",
    content_count: 10,
    raw_score: 82,
    trust_aware_score: 76,
    high_risk_content_ratio: 0.3,
  },
  aspects: [{
    name: "降噪",
    trust_aware_score: 80,
    mention_count: 6,
    positive_ratio: 0.7,
    neutral_ratio: 0.2,
    negative_ratio: 0.1,
    evidence_ids: ["e1"],
  }],
  recommended_sources: [{
    post_id: "note-1",
    platform: "xiaohongshu",
    title: "推荐阅读",
    publish_time: "2026-07-20",
    relevance: 0.95,
    risk_score: 10,
    url: "https://www.xiaohongshu.com/explore/note-1",
    evidence_ids: ["e1"],
  }],
  evidence_details: [{
    evidence_id: "e1",
    post_id: "note-1",
    platform: "xiaohongshu",
    title: "真实体验",
    quote: "降噪表现稳定",
    context: "通勤使用",
    publish_time: "2026-07-20",
    sentiment: "positive",
    risk_level: "low",
    risk_score: 10,
    url: "https://www.xiaohongshu.com/explore/note-1",
  }],
  limitations: ["样本规模有限。"],
  statistics: {
    keywords: [{ text: "降噪", count: 12, weight: 1 }],
    sentiment_distribution: { positive: 0.6, neutral: 0.3, negative: 0.1 },
    risk_ratio: 0.2,
  },
  representative_notes: [{ note_id: "note-1", title: "真实体验", url: "https://www.xiaohongshu.com/explore/note-1", source_url: "http://127.0.0.1:8000/api/v1/xhs/collections/job-1/notes/note-1/open", link_expires_at: "2999-01-01T00:00:00+00:00", score: 0.9, summary: "代表笔记" }],
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
if (normalizedSchema11.sample.risk_negative_ratio !== 0.3) {
  throw new Error(`schema 1.1 LLM risk ratio mapping failed: expected 0.3, got ${normalizedSchema11.sample.risk_negative_ratio}`);
}
if (normalizedSchema11.sample.raw_sentiment_score !== 82 || normalizedSchema11.sample.trust_aware_sentiment_score !== 76) {
  throw new Error("schema 1.1 LLM sentiment score mapping failed");
}
if (normalizedSchema11.sample.confidence !== 0.88) {
  throw new Error(`schema 1.1 LLM confidence mapping failed: expected 0.88, got ${normalizedSchema11.sample.confidence}`);
}
if (normalizedSchema11.high_risk_count !== 3 || normalizedSchema11.risk_reasons[0]?.reason_label !== "营销式表达") {
  throw new Error("schema 1.1 LLM risk overview mapping failed");
}
if (normalizedSchema11.risk_caution !== "风险分数表示内容需要谨慎参考，不代表评论一定虚假。") {
  throw new Error("schema 1.1 LLM risk caution mapping failed");
}
if (normalizedSchema11.strengths.length !== 3 || normalizedSchema11.strengths[0] !== "降噪表现稳定。") {
  throw new Error("schema 1.1 product pros mapping failed");
}
if (normalizedSchema11.weaknesses.length !== 3 || normalizedSchema11.weaknesses[2] !== "部分场景证据不足。") {
  throw new Error("schema 1.1 product cons mapping failed");
}
if (normalizedSchema11.llm_summary?.purchase_reference?.raw_one_liner !== "原始结论") {
  throw new Error("schema 1.1 purchase reference mapping failed");
}
if (normalizedSchema11.llm_summary?.sample_overview.coverage_note !== "样本仅覆盖小红书。") {
  throw new Error("schema 1.1 sample overview mapping failed");
}
if (normalizedSchema11.llm_summary?.platform?.content_count !== 10) {
  throw new Error("schema 1.1 platform metrics mapping failed");
}
if (normalizedSchema11.llm_summary?.aspects[0]?.evidence_ids[0] !== "e1") {
  throw new Error("schema 1.1 aspect evidence mapping failed");
}
if (normalizedSchema11.llm_summary?.recommended_sources[0]?.title !== "推荐阅读") {
  throw new Error("schema 1.1 recommended sources mapping failed");
}
if (normalizedSchema11.llm_summary?.evidence_details[0]?.context !== "通勤使用") {
  throw new Error("schema 1.1 evidence details mapping failed");
}
if (normalizedSchema11.llm_summary?.limitations[0] !== "样本规模有限。") {
  throw new Error("schema 1.1 limitations mapping failed");
}
if (normalizedSchema11.keywords[0] !== "降噪") {
  throw new Error("schema 1.1 statistics.keywords mapping failed");
}
if (normalizedSchema11.evidence[0]?.source_url !== "http://127.0.0.1:8000/api/v1/xhs/collections/job-1/notes/note-1/open") {
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
if (normalizedSchema11.evidence[0]?.link_expires_at !== "2999-01-01T00:00:00+00:00") {
  throw new Error("schema 1.1 temporary source expiry mapping failed");
}
const temporarySourceUrl = normalizedSchema11.evidence[0]?.source_url ?? "";
if (sourceLinkProblem(temporarySourceUrl, "2999-01-01T00:00:00+00:00") !== null) {
  throw new Error("valid temporary source URL should open");
}
if (sourceLinkProblem(temporarySourceUrl, "2000-01-01T00:00:00+00:00") !== "原文链接已过期，请重新采集。") {
  throw new Error("expired temporary source URL should be blocked");
}
if (sourceLinkProblem(temporarySourceUrl, null) !== "本次采集未获得可用原文链接，请重新采集。") {
  throw new Error("temporary source URL without expiry should be blocked");
}
if (sourceLinkProblem("https://www.xiaohongshu.com/explore/note-1", null) !== null) {
  throw new Error("ordinary external source URL should retain its current behavior");
}

console.log("verify-frontend-contract: ok");
