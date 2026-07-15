from typing import Annotated, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ==========================================
# 1. 通用枚举与基础类型
# ==========================================
DataMode = Literal["realtime", "cache", "demo"]
SentimentLabel = Literal["positive", "negative", "neutral"]
SafetyLevel = Literal["low", "medium", "high"]
EmptyCode = Literal[
    "page_unsupported",
    "product_unrecognized",
    "analysis_not_ready",
    "backend_unavailable",
    "retryable_error",
    "no_aspect_data",
    "no_platform_data",
    "no_source_data",
    "no_evidence_data",
]

ScoreFloat = Annotated[float, Field(ge=0.0, le=1.0)]


# ==========================================
# 2. 顶部状态
# ==========================================
class RefreshTask(BaseModel):
    progress: ScoreFloat = Field(..., description="分析任务进度，范围 0.0 ~ 1.0")
    stage: str = Field(..., description="当前阶段，例如：抓取内容、清洗文本、模型推理")
    eta_seconds: Optional[int] = Field(default=None, description="预计剩余时间（秒）")


class StatusSection(BaseModel):
    data_mode: DataMode = Field(..., alias="dataMode", description="当前数据模式")
    updated_at: Optional[str] = Field(default=None, alias="updatedAt", description="分析更新时间")
    refresh_task: Optional[RefreshTask] = Field(default=None, alias="refreshTask", description="刷新分析任务进度")
    cache_hint: Optional[str] = Field(default=None, alias="cacheHint", description="缓存提示")
    partial_platform_failure: Optional[str] = Field(default=None, alias="partialPlatformFailure", description="部分平台失败提示")
    update_message: Optional[str] = Field(default=None, alias="updateMessage", description="更新成功或失败提示")


# ==========================================
# 3. 商品信息
# ==========================================
class ProductInfo(BaseModel):
    image_url: Optional[str] = Field(default=None, alias="imageUrl", description="商品图片链接")
    name: str = Field(..., description="商品规范名称")
    brand: Optional[str] = Field(default=None, description="品牌")
    model: Optional[str] = Field(default=None, description="型号")
    recognition_status: str = Field(..., alias="recognitionStatus", description="商品识别状态")
    match_confidence: ScoreFloat = Field(..., alias="matchConfidence", description="商品匹配置信度")


# ==========================================
# 4. 一句话购买参考
# ==========================================
class PurchaseReference(BaseModel):
    trust_summary: str = Field(..., alias="trustSummary", description="Trust-aware 一句话总结")
    raw_summary: str = Field(..., alias="rawSummary", description="Raw 一句话总结")
    active_mode: Literal["raw", "trust-aware"] = Field(..., alias="activeMode", description="当前切换状态")
    reason_for_change: Optional[str] = Field(default=None, alias="reasonForChange", description="两种结论变化的原因")
    evidence_clickable: bool = Field(default=True, alias="evidenceClickable", description="可点击查看对应结论的证据")


# ==========================================
# 5. 综合评分
# ==========================================
class ScoreSummary(BaseModel):
    raw_score: ScoreFloat = Field(..., alias="rawScore", description="Raw 情感评分")
    trust_score: ScoreFloat = Field(..., alias="trustScore", description="Trust-aware 情感评分")
    confidence: ScoreFloat = Field(..., description="分析置信度")
    note: str = Field(..., description="说明：分数反映评价情感倾向，不是商品客观质量分")


# ==========================================
# 6. 平台对比
# ==========================================
class PlatformComparison(BaseModel):
    platform: Literal["淘宝", "小红书", "B站"] = Field(..., description="平台名称")
    content_count: int = Field(..., alias="contentCount", description="内容数量")
    raw_score: ScoreFloat = Field(..., alias="rawScore", description="Raw 评分")
    trust_score: ScoreFloat = Field(..., alias="trustScore", description="Trust-aware 评分")
    high_risk_ratio: ScoreFloat = Field(..., alias="highRiskRatio", description="高风险内容比例")


# ==========================================
# 7. 方面评价
# ==========================================
class AspectEvaluation(BaseModel):
    aspect_name: str = Field(..., alias="aspectName", description="方面名称")
    trust_score: ScoreFloat = Field(..., alias="trustScore", description="Trust-aware 评分")
    mention_count: int = Field(..., alias="mentionCount", description="提及数量")
    positive_ratio: ScoreFloat = Field(..., alias="positiveRatio", description="正面比例")
    neutral_ratio: ScoreFloat = Field(..., alias="neutralRatio", description="中性比例")
    negative_ratio: ScoreFloat = Field(..., alias="negativeRatio", description="负面比例")
    high_platform_divergence: bool = Field(default=False, alias="highPlatformDivergence", description="平台分歧较高提示")
    evidence_clickable: bool = Field(default=True, alias="evidenceClickable", description="点击后可查看该方面的证据")


# ==========================================
# 8. 风险说明
# ==========================================
class RiskReasonDistribution(BaseModel):
    reason: str = Field(..., description="风险原因，例如营销式表达、内容重复、上下文不足")
    count: int = Field(..., description="数量")


class RiskSection(BaseModel):
    high_risk_count: int = Field(..., alias="highRiskCount", description="高风险内容数量")
    high_risk_ratio: ScoreFloat = Field(..., alias="highRiskRatio", description="高风险内容比例")
    reasons: List[RiskReasonDistribution] = Field(default_factory=list, description="风险原因分布")
    note: str = Field(..., description="固定提示：风险分数表示内容需要谨慎参考，不代表评论一定虚假。")


# ==========================================
# 9. 推荐来源
# ==========================================
class RecommendedSource(BaseModel):
    platform: Literal["淘宝", "小红书", "B站"] = Field(..., description="来源平台")
    title: str = Field(..., description="来源标题")
    published_at: Optional[str] = Field(default=None, alias="publishedAt", description="发布时间")
    relevance: ScoreFloat = Field(..., description="相关度")
    risk_score: ScoreFloat = Field(..., alias="riskScore", description="风险分数")
    url: str = Field(..., description="原始链接")


# ==========================================
# 10. 证据详情抽屉
# ==========================================
class EvidenceDetail(BaseModel):
    platform: Literal["淘宝", "小红书", "B站"] = Field(..., description="来源平台")
    title: str = Field(..., description="来源标题")
    quote: str = Field(..., description="引用原文")
    context: Optional[str] = Field(default=None, description="上下文")
    published_at: Optional[str] = Field(default=None, alias="publishedAt", description="发布时间")
    sentiment: SentimentLabel = Field(..., description="情感倾向")
    risk_level: SafetyLevel = Field(..., alias="riskLevel", description="风险等级")
    risk_score: ScoreFloat = Field(..., alias="riskScore", description="风险分数")
    url: str = Field(..., description="原文链接")


# ==========================================
# 11. 空状态与错误状态
# ==========================================
class EmptyState(BaseModel):
    code: EmptyCode = Field(..., description="错误或空状态代码")
    message: str = Field(..., description="描述信息")
    retryable: bool = Field(default=False, description="是否可重试")


# ==========================================
# 12. 最终前端展示包装类
# ==========================================
class SidePanelDisplay(BaseModel):
    """
    面板展示接口的最终返回类型。
    这是前端页面真正消费的稳定结构，适合在 Side Panel 里自上而下渲染。
    """
    status: Optional[StatusSection] = Field(default=None, description="顶部状态")
    product: Optional[ProductInfo] = Field(default=None, description="商品信息")
    purchase_reference: Optional[PurchaseReference] = Field(default=None, alias="purchaseReference", description="一句话购买参考")
    scores: Optional[ScoreSummary] = Field(default=None, description="综合评分")
    platforms: List[PlatformComparison] = Field(default_factory=list, description="平台对比")
    aspects: List[AspectEvaluation] = Field(default_factory=list, description="方面评价")
    risk: Optional[RiskSection] = Field(default=None, description="风险说明")
    sources: List[RecommendedSource] = Field(default_factory=list, description="推荐来源")
    evidence_drawer: List[EvidenceDetail] = Field(default_factory=list, alias="evidenceDrawer", description="证据详情抽屉")
    empty_state: Optional[EmptyState] = Field(default=None, alias="emptyState", description="异常与空状态")

    model_config = ConfigDict(populate_by_name=True)
