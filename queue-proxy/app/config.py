import os
from dataclasses import dataclass, field


def _csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in os.getenv(name, default).split(",") if p.strip())


@dataclass(frozen=True)
class Settings:
    # Upstream LiteLLM (private .internal in prod; localhost in dev)
    litellm_base_url: str = os.getenv("LITELLM_BASE_URL", "http://127.0.0.1:4000")
    litellm_master_key: str = os.getenv("LITELLM_MASTER_KEY", "")

    port: int = int(os.getenv("PORT", "8080"))

    # Queue behaviour
    max_wait_seconds: float = float(os.getenv("MAX_WAIT_SECONDS", "120"))
    budget_poll_seconds: float = float(os.getenv("BUDGET_POLL_SECONDS", "5"))
    scheduler_tick_seconds: float = float(os.getenv("SCHEDULER_TICK_SECONDS", "0.05"))
    window_seconds: float = float(os.getenv("WINDOW_SECONDS", "60"))

    # Auth/info cache
    auth_cache_ttl: float = float(os.getenv("AUTH_CACHE_TTL", "30"))
    user_cache_ttl: float = float(os.getenv("USER_CACHE_TTL", "10"))

    # Fallbacks if LiteLLM doesn't report limits
    default_key_rpm: int = int(os.getenv("DEFAULT_KEY_RPM", "60"))
    default_user_rpm: int = int(os.getenv("DEFAULT_USER_RPM", "0"))  # 0 = unlimited

    # Test-mode overrides (0 = disabled): force limits regardless of LiteLLM,
    # useful with a short WINDOW_SECONDS to exercise the queue quickly.
    force_user_rpm: int = int(os.getenv("FORCE_USER_RPM", "0"))
    force_key_rpm: int = int(os.getenv("FORCE_KEY_RPM", "0"))

    # Only these paths are queued; everything else is proxied straight through.
    inference_paths: tuple[str, ...] = field(
        default_factory=lambda: _csv(
            "INFERENCE_PATHS",
            "/v1/chat/completions,/v1/completions",
        )
    )


settings = Settings()
