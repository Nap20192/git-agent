from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# langchain/langsmith/langfuse читают ключи из os.environ — грузим .env туда
load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Трейсинг (LANGSMITH_*/LANGFUSE_*) читает core/tracing/config.py напрямую
    # из env — здесь не дублируем, чтобы не было двух источников правды.

    # OpenSandbox
    opensandbox_domain: str = "localhost:8090"
    opensandbox_api_key: str = ""

    # Postgres
    database_url: str = "postgresql://git_agent:git_agent@localhost:5433/git_agent"

    # HTTP-gateway (main.py:app)
    server_host: str = "0.0.0.0"
    server_port: int = 8080

    # LLM (OpenAI-совместимый endpoint; переопределяются флагами CLI на каждый ран)
    llm_api_base: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    # Образ песочницы для сканирования (нужен git + coreutils)
    sandbox_image: str = "alpine/git:latest"

    # MCP: путь к cve-mcp-server (stdio через `uv run --project`); пусто = выкл.
    cve_mcp_path: str = ""
    nvd_api_key: str = ""  # прокидывается в env cve-mcp (опционально)

    # Раннер (консьюмер Событий; см. openspec/specs/runner)
    rabbit_url: str = "amqp://guest:guest@localhost:5673/"
    runner_name: str = "runner-1"
    runner_address: str = "http://localhost:8081"
    runner_port: int = 8081
    runner_slots: int = 2
    runner_idle_timeout_seconds: float = 900.0
    runner_token: str = ""  # X-Runner-Token для backend
    backend_url: str = ""  # hub; пусто = регистрация/heartbeat выключены
    hub_enc_key: str = ""  # base64 32 байта, AES-GCM для hub.*_enc


settings = Settings()
