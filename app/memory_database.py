from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .config import get_settings

settings = get_settings()

MEMORY_DATABASE_URL = (
    f"mysql+pymysql://{settings.memory_db_user}:{settings.memory_db_password}"
    f"@{settings.memory_db_host}:{settings.memory_db_port}/{settings.memory_db_name}"
)

memory_engine = create_engine(
    MEMORY_DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
)

MemorySessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=memory_engine)


def get_memory_db():
    """Dependency para obtener sesión de la DB de memory."""
    db = MemorySessionLocal()
    try:
        yield db
    finally:
        db.close()
