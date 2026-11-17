from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./sierra.db"
    demo_mode: bool = True
    demo_password: str = "trail-demo"
    coupon_secret: str = "local-demo-only-change-me"
    cookie_secure: bool = False
    allowed_origins: str = "http://localhost:8000,http://127.0.0.1:8000,http://localhost:5173,http://127.0.0.1:5173"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"
    llm_timeout_seconds: float = 2.5
    request_timeout_seconds: float = 8.0
    session_hours: int = 12
    memory_char_budget: int = 12000
    order_data_path: Path | None = None
    data_dir: Path = ROOT / "data"
    frontend_dir: Path = ROOT / "frontend" / "dist"

    def validate_runtime(self):
        if not self.demo_mode:
            if self.coupon_secret == "local-demo-only-change-me" or len(self.coupon_secret) < 32:
                raise ValueError("Non-demo mode requires a private COUPON_SECRET of at least 32 characters")
            if not self.cookie_secure:
                raise ValueError("Non-demo mode requires COOKIE_SECURE=true behind HTTPS")
