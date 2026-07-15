from pathlib import Path


class ImageProcessor:
    """Sample image preprocessing component."""

    @staticmethod
    def resize(image_path: str, output_dir: str = "tmp") -> str:
        path = Path(image_path)
        output = Path(output_dir) / f"processed_{path.name}"
        output.parent.mkdir(parents=True, exist_ok=True)
        return str(output)
