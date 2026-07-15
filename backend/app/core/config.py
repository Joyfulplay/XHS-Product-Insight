from dataclasses import dataclass


@dataclass
class Settings:
    app_name: str = "XHS-Product-Insight"
    debug: bool = True
    llm_model: str = "gpt-4o-mini"


settings = Settings()
