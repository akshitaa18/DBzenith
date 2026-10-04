from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "DBZenith"
    app_env: str = "development"
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5174",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
            "http://localhost:8080",
            "http://127.0.0.1:8080",
        ]
    )
    database_url: str = "postgresql+psycopg://dbzenith:change_me_dev_only@localhost:5432/dbzenith"
    sandbox_database_url: str = "postgresql+psycopg://dbzenith_sandbox:change_me_sandbox_only@localhost:5433/dbzenith_sandbox"
    slow_query_threshold_ms: float = 100.0
    telemetry_interval_seconds: int = 30
    telemetry_query_limit: int = 500
    telemetry_relation_limit: int = 100
    collect_explain: bool = True
    explain_query_limit: int = 50
    simulation_max_rows_per_table: int = 25_000
    simulation_max_timeout_ms: int = 30_000
    simulation_max_benchmark_runs: int = 5
    secret_key: str = Field(default_factory=lambda: "dbzenith_secure_dev_hmac_secret_key_change_in_prod_32bytes")
    token_ttl_seconds: int = 86400
    api_rate_limit_per_minute: int = 120
    auth_rate_limit_per_minute: int = 20

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
