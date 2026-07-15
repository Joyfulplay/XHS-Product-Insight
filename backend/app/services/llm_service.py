class LLMService:
    """Sample service class responsible for LLM invocation."""

    def __init__(self, model_name: str = "gpt-4o-mini"):
        self.model_name = model_name

    def generate(self, prompt: str) -> str:
        return f"Mock LLM response for prompt: {prompt[:80]}"
