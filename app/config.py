from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_host: str = "localhost"
    database_port: int = 3306
    database_name: str = "qdrant_forms"
    database_user: str = "qdrant_forms"
    database_password: str = ""

    # Memory DB (editor de temas/subtemas/bloques)
    memory_db_host: str = "localhost"
    memory_db_port: int = 3306
    memory_db_name: str = "memory"
    memory_db_user: str = "root"
    memory_db_password: str = ""

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""

    # n8n
    n8n_webhook_url: str = ""

    # JWT
    secret_key: str = "tu_secret_key_muy_seguro_cambiar_en_produccion"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24 horas

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
