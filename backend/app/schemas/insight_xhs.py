from typing import Annotated, Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


ScoreFloat = Annotated[float, Field(ge=0.0, le=1.0)]


# ==========================================
# 1. AI 输出输入（统一给模型的输入）
# ==========================================
class XhsSentimentInput(BaseModel):
    """
    AI 分析输入结构。
    这里是模型真正需要的原始信息，尽量保留完整上下文，方便话术生成与证据抽取。
    """
    post_id: str = Field(..., description="帖子唯一 ID")
    title: str = Field(..., description="帖子标题", min_length=1)
    content: str = Field(..., description="帖子正文/评论内容", min_length=1)
    platform: str = Field(default="xhs", description="来源平台")
    author: Optional[str] = Field(default=None, description="作者")
    likes: Optional[int] = Field(default=0, description="点赞数")
    collects: Optional[int] = Field(default=0, description="收藏数")
    comments: Optional[int] = Field(default=0, description="评论数")
    views: Optional[int] = Field(default=0, description="浏览量")
    publish_time: Optional[str] = Field(default=None, description="发布时间")
    tags: List[str] = Field(default_factory=list, description="帖子标签")
    image_urls: List[str] = Field(default_factory=list, description="图片链接列表")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "post_id": "xhs_6688abcde123",
            "title": "家人们，这款控油洗发水我真的栓Q了...",
            "content": "前天看风很大入了这个洗发水。控油确实还可以，撑个两天没问题（给个大拇指）。但是！这个味道也太香得冲脑壳了吧，洗完一整天都头晕。而且洗完头发巨涩，像枯草一样。不推荐购买！",
            "platform": "xhs",
            "author": "小明同学",
            "likes": 120,
            "collects": 45,
            "comments": 18,
            "views": 3580,
            "publish_time": "2026-07-15T09:00:00Z",
            "tags": ["洗发水", "控油", "护发"],
            "image_urls": ["https://example.com/1.jpg"],
        }
    })


# ==========================================
# 2. AI 输出模型（面向模型生成，不直接等于 UI 结构）
# ==========================================
class XhsSentimentOutput(BaseModel):
    """
    AI 产出更新时需要返回的结构化结果。
    这里的字段语义更偏“分析结论”，然后再由 display.py 映射到 Side Panel 展示结构。
    """
    post_id: str = Field(..., description="帖子唯一 ID")
    product_name: Optional[str] = Field(default=None, description="识别出的商品规范名")
    brand: Optional[str] = Field(default=None, description="品牌")
    model: Optional[str] = Field(default=None, description="型号")
    product_match_confidence: Optional[ScoreFloat] = Field(default=None, description="商品识别置信度，0~1")
    raw_summary: str = Field(..., description="Raw 一句话总结")
    trust_summary: str = Field(..., description="Trust-aware 一句话总结")
    reason_for_change: Optional[str] = Field(default=None, description="两种结论变化的原因")
    overall_sentiment_raw: str = Field(..., description="Raw 整体情感标签，例如 positive / negative / neutral")
    overall_sentiment_trust: str = Field(..., description="Trust-aware 整体情感标签")
    raw_score: ScoreFloat = Field(..., description="Raw 情感评分")
    trust_score: ScoreFloat = Field(..., description="Trust-aware 情感评分")
    confidence: ScoreFloat = Field(..., description="整体分析置信度")
    platform_comparison: List[Dict[str, Any]] = Field(default_factory=list, description="各平台对比结果")
    aspect_evaluations: List[Dict[str, Any]] = Field(default_factory=list, description="各方面评价结果")
    risk_summary: Dict[str, Any] = Field(default_factory=dict, description="风险说明结果")
    sources: List[Dict[str, Any]] = Field(default_factory=list, description="推荐来源列表")
    evidence_details: List[Dict[str, Any]] = Field(default_factory=list, description="证据详情列表")
    status_message: Optional[str] = Field(default=None, description="状态说明")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "post_id": "xhs_6688abcde123",
            "product_name": "控油洗发水",
            "brand": "某品牌",
            "model": "A1",
            "product_match_confidence": 0.92,
            "raw_summary": "用户整体偏负面，主要投诉气味和洗后发涩。",
            "trust_summary": "在去除营销式表达与重复内容后，结论仍偏负面，核心风险集中在气味与湿发体验。",
            "reason_for_change": "Trust-aware 模式过滤了过度营销表述和重复内容，减少了噪声后更准确地识别出真实投诉点。",
            "overall_sentiment_raw": "negative",
            "overall_sentiment_trust": "negative",
            "raw_score": 0.82,
            "trust_score": 0.74,
            "confidence": 0.89,
            "platform_comparison": [
                {
                    "platform": "小红书",
                    "content_count": 12,
                    "raw_score": 0.71,
                    "trust_score": 0.68,
                    "high_risk_ratio": 0.17,
                }
            ],
            "aspect_evaluations": [
                {
                    "aspect_name": "气味",
                    "trust_score": 0.18,
                    "mention_count": 9,
                    "positive_ratio": 0.11,
                    "neutral_ratio": 0.0,
                    "negative_ratio": 0.89,
                    "high_platform_divergence": True,
                }
            ],
            "risk_summary": {
                "high_risk_count": 3,
                "high_risk_ratio": 0.25,
                "reasons": [
                    {"reason": "营销式表达", "count": 1},
                    {"reason": "内容重复", "count": 1},
                    {"reason": "上下文不足", "count": 1},
                ],
            },
            "sources": [
                {
                    "platform": "小红书",
                    "title": "这款洗发水真的控油吗？",
                    "published_at": "2026-07-15T09:30:00Z",
                    "relevance": 0.92,
                    "risk_score": 0.21,
                    "url": "https://example.com/source/1",
                }
            ],
            "evidence_details": [
                {
                    "platform": "小红书",
                    "title": "这款洗发水真的控油吗？",
                    "quote": "这个味道也太香得冲脑壳了吧",
                    "context": "用户在购买后表达明显不适",
                    "published_at": "2026-07-15T09:30:00Z",
                    "sentiment": "negative",
                    "risk_level": "low",
                    "risk_score": 0.18,
                    "url": "https://example.com/source/1",
                }
            ],
            "status_message": "分析已完成",
        }
    })