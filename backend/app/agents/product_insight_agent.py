class ProductInsightAgent:
    """A sample AI agent class for product insight generation."""

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def analyze(self, text: str, image_paths: list[str] | None = None) -> dict:
        """Return a placeholder analysis result structure."""
        return {
            "summary": text[:120],
            "image_count": len(image_paths or []),
            "insights": [
                "The content appears to contain product-related signals.",
                "Further LLM reasoning can be added here.",
            ],
        }
