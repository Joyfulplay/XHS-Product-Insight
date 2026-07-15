class XHSClient:
    """Sample crawler client placeholder for future data acquisition logic."""

    def __init__(self, base_url: str = "https://example.com"):
        self.base_url = base_url

    def fetch_posts(self, keyword: str) -> list[dict]:
        """Return a placeholder list of fetched data items."""
        return [
            {
                "keyword": keyword,
                "content": "Sample raw post content.",
                "images": [],
            }
        ]
