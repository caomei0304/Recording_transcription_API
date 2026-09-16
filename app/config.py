from functools import lru_cache
import os
from pathlib import Path


class Settings:
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    database_path: Path = Path("./data/app.db")
    upload_dir: Path = Path("./data/uploads")
    max_upload_mb: int = 50
    worker_concurrency: int = 3
    transcribe_fail_rate: float = 0.2
    llm_provider: str = "mock"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: int = 20

    def __init__(
        self,
        app_host: str | None = None,
        app_port: int | None = None,
        database_path: Path | str | None = None,
        upload_dir: Path | str | None = None,
        max_upload_mb: int | None = None,
        worker_concurrency: int | None = None,
        transcribe_fail_rate: float | None = None,
        llm_provider: str | None = None,
        llm_base_url: str | None = None,
        llm_api_key: str | None = None,
        llm_model: str | None = None,
        llm_timeout_seconds: int | None = None,
    ):
        load_dotenv()
        defaults = type(self)
        self.app_host = app_host or os.getenv("APP_HOST", defaults.app_host)
        self.app_port = app_port or int(os.getenv("APP_PORT", defaults.app_port))
        self.database_path = Path(database_path or os.getenv("DATABASE_PATH", str(defaults.database_path)))
        self.upload_dir = Path(upload_dir or os.getenv("UPLOAD_DIR", str(defaults.upload_dir)))
        self.max_upload_mb = max_upload_mb or int(os.getenv("MAX_UPLOAD_MB", defaults.max_upload_mb))
        self.worker_concurrency = worker_concurrency or int(os.getenv("WORKER_CONCURRENCY", defaults.worker_concurrency))
        self.transcribe_fail_rate = transcribe_fail_rate
        if self.transcribe_fail_rate is None:
            self.transcribe_fail_rate = float(os.getenv("TRANSCRIBE_FAIL_RATE", defaults.transcribe_fail_rate))
        self.transcribe_fail_rate = min(1.0, max(0.0, self.transcribe_fail_rate))
        self.llm_provider = llm_provider or os.getenv("LLM_PROVIDER", defaults.llm_provider)
        self.llm_base_url = llm_base_url or os.getenv("LLM_BASE_URL", defaults.llm_base_url)
        self.llm_api_key = llm_api_key if llm_api_key is not None else os.getenv("LLM_API_KEY", defaults.llm_api_key)
        self.llm_model = llm_model or os.getenv("LLM_MODEL", defaults.llm_model)
        self.llm_timeout_seconds = llm_timeout_seconds or int(
            os.getenv("LLM_TIMEOUT_SECONDS", defaults.llm_timeout_seconds)
        )

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
