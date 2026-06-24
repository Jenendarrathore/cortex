from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).parent.parent.parent / ".env"  # cortex/.env


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    pghost: str = "localhost"
    pgport: int = 5432
    pgdatabase: str = "cortex_rag"
    pguser: str = "raguser"
    pgpassword: str = ""

    ollama_url: str = "http://localhost:11434"
    embed_model: str = "nomic-embed-text"
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    chunk_max_tokens: int = 400
    chunk_overlap_chars: int = 200
    vector_search_limit: int = 50
    fts_search_limit: int = 50
    rerank_top_n: int = 20

    # Embeddings transport
    ollama_timeout: float = 60.0
    embed_max_retries: int = 1  # one retry, then fail fast (see plan: local Ollama won't self-heal)

    # Operational
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173"  # comma-separated; "*" allows all

    redis_url: str = "redis://localhost:6379"

    # Optional API key — if set, all routes require X-API-Key header
    api_key: str = ""

    # License enforcement — OFF by default. The open-source build boots with no
    # license. Set LICENSE_ENABLED=true only if you run a license server.
    license_enabled: bool = False
    license_key: str = ""
    license_server_url: str = "https://license.yourdomain.com"
    license_check_interval_hours: int = 24

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.pguser}:{self.pgpassword}"
            f"@{self.pghost}:{self.pgport}/{self.pgdatabase}"
        )


settings = Settings()
