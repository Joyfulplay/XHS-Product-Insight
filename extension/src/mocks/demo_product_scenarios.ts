import type { Aspect, DemoProductScenario, PlatformComparison, ProductAnalysisData, RiskReason, TopSource } from "../api/types";

type DemoAspectCode =
  | "sound_quality"
  | "noise_cancellation"
  | "battery_life"
  | "connection_stability"
  | "comfort"
  | "microphone"
  | "build_quality"
  | "price_value";

type AspectInput = {
  code: DemoAspectCode;
  label: string;
  score: number;
  mentions: number;
  disagreement: number;
};

const platforms = ["taobao", "xiaohongshu", "bilibili"] as const;

function aspect(input: AspectInput): Aspect {
  const positive = Math.max(0.36, Math.min(0.9, input.score / 115));
  const negative = Math.max(0.04, Math.min(0.32, (100 - input.score) / 140));
  return {
    aspect_code: input.code,
    aspect_label: input.label,
    mention_count: input.mentions,
    raw_sentiment_score: Math.min(100, input.score + 4),
    trusted_sentiment_score: input.score,
    positive_ratio: Number(positive.toFixed(2)),
    neutral_ratio: Number(Math.max(0.06, 1 - positive - negative).toFixed(2)),
    negative_ratio: Number(negative.toFixed(2)),
    platform_disagreement_score: input.disagreement,
    top_claim_ids: [`claim_${input.code}`],
    evidence_content_ids: [`ev_${input.code}`],
  };
}

function comparison(taobao: number, xhs: number, bilibili: number, risk: [number, number, number]): PlatformComparison[] {
  return [
    { platform: "taobao", content_count: 820, raw_sentiment_score: taobao + 5, trusted_sentiment_score: taobao, high_risk_ratio: risk[0] },
    { platform: "xiaohongshu", content_count: 236, raw_sentiment_score: xhs + 7, trusted_sentiment_score: xhs, high_risk_ratio: risk[1] },
    { platform: "bilibili", content_count: 118, raw_sentiment_score: bilibili + 3, trusted_sentiment_score: bilibili, high_risk_ratio: risk[2] },
  ];
}

function sources(prefix: string, titles: [string, string, string], risks: [number, number, number]): TopSource[] {
  return [
    {
      content_id: `${prefix}_source_1`,
      platform: platforms[0],
      source_title: titles[0],
      source_url: "https://item.taobao.com/",
      publish_time: "2026-07-12T10:20:00+08:00",
      relevance_score: 0.94,
      risk_score: risks[0],
    },
    {
      content_id: `${prefix}_source_2`,
      platform: platforms[1],
      source_title: titles[1],
      source_url: "https://www.xiaohongshu.com/",
      publish_time: "2026-07-13T11:20:00+08:00",
      relevance_score: 0.9,
      risk_score: risks[1],
    },
    {
      content_id: `${prefix}_source_3`,
      platform: platforms[2],
      source_title: titles[2],
      source_url: "https://www.bilibili.com/",
      publish_time: "2026-07-14T12:20:00+08:00",
      relevance_score: 0.86,
      risk_score: risks[2],
    },
  ];
}

function analysis(config: {
  id: string;
  name: string;
  brand: string;
  model: string;
  raw: number;
  trusted: number;
  confidence: number;
  rawSummary: string;
  trustSummary: string;
  changedReason: string;
  aspects: AspectInput[];
  platformComparison: PlatformComparison[];
  riskReasons: RiskReason[];
  riskRatio: number;
  topSources: TopSource[];
  updatedAt: string;
}): ProductAnalysisData {
  return {
    analysis_id: `ana_${config.id}`,
    product: {
      product_id: `demo_${config.id}`,
      canonical_name: config.name,
      brand: config.brand,
      model: config.model,
      display_image_url: null,
    },
    analysis_status: "ready",
    data_status: { mode: "demo", is_stale: false, platform_failures: [] },
    coverage: { total_content_count: 1174, platforms: ["taobao", "xiaohongshu", "bilibili"] },
    overview: { raw_sentiment_score: config.raw, trusted_sentiment_score: config.trusted, confidence: config.confidence },
    summaries: {
      raw: { one_sentence_summary: config.rawSummary },
      trust_aware: { one_sentence_summary: config.trustSummary },
      changed_claims: [
        { claim_id: `claim_${config.id}`, text: "平台种草内容中的绝对化推荐", reason: config.changedReason },
      ],
    },
    platform_comparison: config.platformComparison,
    aspects: config.aspects.map(aspect),
    risk_summary: {
      high_risk_count: Math.round(1174 * config.riskRatio),
      high_risk_ratio: config.riskRatio,
      risk_reason_distribution: config.riskReasons,
      display_note: "当前为蓝牙耳机演示数据，风险分数用于解释可信感知降权，不代表内容一定虚假。",
    },
    top_sources: config.topSources,
    updated_at: config.updatedAt,
  };
}

export const demoProductScenarios: DemoProductScenario[] = [
  {
    scenario_id: "commute_noise_cancelling",
    display_name: "通勤降噪型",
    description: "降噪强、音质较好，适合地铁通勤和开放办公区，但价格偏高且长时间佩戴评价分歧明显。",
    analysis: analysis({
      id: "commute_noise_cancelling",
      name: "Auraloop NC Pro 通勤降噪耳机",
      brand: "Auraloop",
      model: "NC Pro",
      raw: 87,
      trusted: 80,
      confidence: 0.88,
      rawSummary: "整体评价集中称赞降噪和沉浸感，是通勤场景下存在感很强的降噪耳机。",
      trustSummary: "可信评价显示降噪表现突出、音质稳定，但舒适度和价格争议会影响长时间使用体验。",
      changedReason: "部分“全天无感佩戴”和“同价位无敌”的表述来自营销式内容，可信感知后被降权。",
      aspects: [
        { code: "noise_cancellation", label: "降噪", score: 92, mentions: 642, disagreement: 0.12 },
        { code: "sound_quality", label: "音质", score: 84, mentions: 511, disagreement: 0.2 },
        { code: "battery_life", label: "续航", score: 78, mentions: 305, disagreement: 0.24 },
        { code: "connection_stability", label: "连接稳定", score: 82, mentions: 229, disagreement: 0.18 },
        { code: "comfort", label: "舒适度", score: 63, mentions: 388, disagreement: 0.61 },
        { code: "microphone", label: "通话效果", score: 70, mentions: 196, disagreement: 0.42 },
        { code: "build_quality", label: "做工质感", score: 83, mentions: 214, disagreement: 0.22 },
        { code: "price_value", label: "性价比", score: 55, mentions: 274, disagreement: 0.52 },
      ],
      platformComparison: comparison(83, 77, 81, [0.08, 0.21, 0.07]),
      riskReasons: [
        { reason_code: "promotional_language", reason_label: "营销式表达", count: 92 },
        { reason_code: "duplicate_pattern", reason_label: "内容模式重复", count: 48 },
        { reason_code: "price_context_missing", reason_label: "价格上下文不足", count: 31 },
      ],
      riskRatio: 0.15,
      topSources: sources("commute", ["地铁通勤降噪体验反馈", "办公室降噪耳机一周记录", "旗舰降噪耳机横评片段"], [0.1, 0.22, 0.08]),
      updatedAt: "2026-07-16T09:40:00+08:00",
    }),
  },
  {
    scenario_id: "balanced_value",
    display_name: "均衡性价比型",
    description: "各方面表现均衡，价格友好，适合预算敏感且希望少踩坑的用户，降噪不是最强项。",
    analysis: analysis({
      id: "balanced_value",
      name: "SoundMate ValuePods 均衡蓝牙耳机",
      brand: "SoundMate",
      model: "ValuePods",
      raw: 84,
      trusted: 82,
      confidence: 0.84,
      rawSummary: "用户普遍认为它功能够用、价格友好，是入门到中端预算的稳妥选择。",
      trustSummary: "可信评价显示它在性价比、续航和稳定性上更占优，但强噪声环境下的降噪预期需要降低。",
      changedReason: "少量“媲美旗舰降噪”的说法证据不足，降权后结论回到均衡实用。",
      aspects: [
        { code: "noise_cancellation", label: "降噪", score: 74, mentions: 421, disagreement: 0.33 },
        { code: "sound_quality", label: "音质", score: 79, mentions: 468, disagreement: 0.21 },
        { code: "battery_life", label: "续航", score: 82, mentions: 352, disagreement: 0.15 },
        { code: "connection_stability", label: "连接稳定", score: 80, mentions: 262, disagreement: 0.18 },
        { code: "comfort", label: "舒适度", score: 77, mentions: 337, disagreement: 0.24 },
        { code: "microphone", label: "通话效果", score: 73, mentions: 205, disagreement: 0.34 },
        { code: "build_quality", label: "做工质感", score: 75, mentions: 196, disagreement: 0.28 },
        { code: "price_value", label: "性价比", score: 91, mentions: 544, disagreement: 0.11 },
      ],
      platformComparison: comparison(84, 79, 82, [0.06, 0.13, 0.05]),
      riskReasons: [
        { reason_code: "overclaim", reason_label: "效果夸大", count: 46 },
        { reason_code: "duplicate_pattern", reason_label: "内容模式重复", count: 29 },
        { reason_code: "missing_context", reason_label: "使用场景不足", count: 22 },
      ],
      riskRatio: 0.08,
      topSources: sources("balanced", ["百元价位耳机已购反馈", "通勤和运动混合使用记录", "中端蓝牙耳机避坑横评"], [0.06, 0.12, 0.05]),
      updatedAt: "2026-07-16T10:15:00+08:00",
    }),
  },
  {
    scenario_id: "comfort_first",
    display_name: "舒适佩戴型",
    description: "舒适度高、续航较好，适合长时间办公和睡前使用，但主动降噪能力相对一般。",
    analysis: analysis({
      id: "comfort_first",
      name: "CloudFit Air Lite 舒适佩戴耳机",
      brand: "CloudFit",
      model: "Air Lite",
      raw: 83,
      trusted: 81,
      confidence: 0.86,
      rawSummary: "评价重点集中在轻盈、耳压低和续航可靠，长时间佩戴反馈明显优于多数入耳式耳机。",
      trustSummary: "可信评价显示它适合长时间佩戴和轻度通勤，若核心需求是强降噪则不应把它作为首选。",
      changedReason: "部分内容把舒适体验延伸为“全场景旗舰”，可信证据更支持长时间佩戴优势。",
      aspects: [
        { code: "noise_cancellation", label: "降噪", score: 66, mentions: 318, disagreement: 0.4 },
        { code: "sound_quality", label: "音质", score: 80, mentions: 452, disagreement: 0.2 },
        { code: "battery_life", label: "续航", score: 87, mentions: 398, disagreement: 0.12 },
        { code: "connection_stability", label: "连接稳定", score: 79, mentions: 241, disagreement: 0.2 },
        { code: "comfort", label: "舒适度", score: 94, mentions: 619, disagreement: 0.09 },
        { code: "microphone", label: "通话效果", score: 76, mentions: 187, disagreement: 0.31 },
        { code: "build_quality", label: "做工质感", score: 78, mentions: 203, disagreement: 0.23 },
        { code: "price_value", label: "性价比", score: 72, mentions: 266, disagreement: 0.29 },
      ],
      platformComparison: comparison(82, 83, 79, [0.05, 0.1, 0.04]),
      riskReasons: [
        { reason_code: "scenario_overfit", reason_label: "场景泛化过度", count: 39 },
        { reason_code: "missing_context", reason_label: "佩戴条件不足", count: 32 },
        { reason_code: "promotional_language", reason_label: "营销式表达", count: 24 },
      ],
      riskRatio: 0.07,
      topSources: sources("comfort", ["长时间办公佩戴体验", "小耳道用户佩戴反馈合集", "轻量耳机续航实测记录"], [0.05, 0.1, 0.04]),
      updatedAt: "2026-07-16T11:05:00+08:00",
    }),
  },
];
