class TextCleaner:
    """Sample text preprocessing component."""

    @staticmethod
    def clean(text: str) -> str:
        cleaned = text.strip()
        cleaned = " ".join(cleaned.split())
        return cleaned
