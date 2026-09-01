from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# langchain/langsmith/langfuse читают ключи из os.environ — грузим .env туда
load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LangSmith (трейсинг включается самим langchain по этим env-переменным)
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "git-agent"

    # Langfuse
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # OpenSandbox
    opensandbox_domain: str = "localhost:8090"
    opensandbox_api_key: str = ""

    # Postgres
    database_url: str = "postgresql://git_agent:git_agent@localhost:5433/git_agent"

    # LLM (OpenAI-совместимый endpoint; переопределяются флагами CLI на каждый ран)
    llm_api_base: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    # Образ песочницы для сканирования (нужен git + coreutils)
    sandbox_image: str = "alpine/git:latest"


settings = Settings()
