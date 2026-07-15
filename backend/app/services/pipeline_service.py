from app.agents.product_insight_agent import ProductInsightAgent
from app.preprocess.cleaner import TextCleaner
from app.preprocess.image_processor import ImageProcessor
from app.services.llm_service import LLMService
from app.services.persistence_service import PersistenceService


class PipelineService:
    """Orchestrates the end-to-end backend analysis workflow."""

    def __init__(self):
        self.text_cleaner = TextCleaner()
        self.image_processor = ImageProcessor()
        self.llm_service = LLMService()
        self.persistence_service = PersistenceService()
        self.agent = ProductInsightAgent(llm_client=self.llm_service)

    def run(self, text: str, image_paths: list[str] | None = None) -> dict:
        cleaned_text = self.text_cleaner.clean(text)
        processed_images = [
            self.image_processor.resize(path) for path in (image_paths or [])
        ]
        result = self.agent.analyze(cleaned_text, processed_images)
        self.persistence_service.save("product_insight", result)
        return result
