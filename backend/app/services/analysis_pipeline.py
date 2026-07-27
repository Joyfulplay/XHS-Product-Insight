"""Pure collection-to-frontend analysis pipeline.

Persistence and request orchestration belong to the connector service. This
module only transforms one completed collection dataset into analysis output.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from app.preprocess.cleaner import ContentCleaner
from app.schemas.analysis_result import AnalysisResult
from app.schemas.llmoutput import XiaohongshuSummaryOutput
from app.LLM.service import XiaohongshuInsightService
from app.services.localAnalysis import LocalAnalysisService

# Reuse Uvicorn's configured error logger so this operational event is visible
# in the backend terminal without requiring an additional logging setup.
logger = logging.getLogger("uvicorn.error")
AnalysisProgressCallback = Callable[[str, float, str], None]


class AnalysisPipelineService:
    """Build a stable frontend response from one completed collection dataset."""

    def __init__(
        self,
        cleaner: ContentCleaner | None = None,
        insight_service_factory: Callable[[], XiaohongshuInsightService] | None = None,
    ) -> None:
        self.local_analysis = LocalAnalysisService(cleaner=cleaner)
        # Preserve the existing attribute for callers that customize the cleaner.
        self.cleaner = self.local_analysis.cleaner
        self.insight_service_factory = insight_service_factory

    def run(self, collection_dataset: dict[str, Any]) -> AnalysisResult:
        result, _ = self.run_with_llm_response(collection_dataset)
        return result

    def run_with_llm_response(
        self,
        collection_dataset: dict[str, Any],
        progress_callback: AnalysisProgressCallback | None = None,
    ) -> tuple[AnalysisResult, dict[str, Any] | None]:
        if progress_callback is not None:
            progress_callback("preparing", 0.05, "正在清洗并准备大模型分析数据")
        local_output = self.local_analysis.run(collection_dataset)
        llm_response = self._build_llm_response(
            collection_dataset,
            local_output.cleaned_notes,
            progress_callback=progress_callback,
        )
        return local_output.result, llm_response

    def _build_llm_response(
        self,
        dataset: dict[str, Any],
        cleaned_notes: list[dict[str, Any]],
        *,
        progress_callback: AnalysisProgressCallback | None = None,
    ) -> dict[str, Any] | None:
        if not cleaned_notes:
            return None

        try:
            insight_service = self._get_insight_service()
        except Exception:
            return None

        raw_input = dataset.get("input") if isinstance(dataset.get("input"), dict) else {}
        product_name = str(
            raw_input.get("query")
            or raw_input.get("product_name")
            or "目标产品"
        )

        try:
            logger.info(
                "[LLM_ANALYSIS_STARTED] 已开始大模型分析：product=%s, note_count=%d",
                product_name,
                min(len(cleaned_notes), 8),
            )
            batch_result = insight_service.analyze_batch(
                product_name,
                cleaned_notes[:8],
                progress_callback=progress_callback,
            )
            summary_json = batch_result.get("summary", {})

            summary = XiaohongshuSummaryOutput.model_validate(summary_json)
            validated_batch_result = {
                **batch_result,
                "summary": summary.model_dump(mode="json"),
            }
            return validated_batch_result
        except Exception:
            logger.exception(
                "[LLM_ANALYSIS_FAILED] 大模型分析或汇总结果校验失败：product=%s",
                product_name,
            )
            return None

    def _get_insight_service(self) -> XiaohongshuInsightService:
        if self.insight_service_factory is not None:
            return self.insight_service_factory()

        from app.LLM.client import LLMClient

        return XiaohongshuInsightService(llm=LLMClient())
