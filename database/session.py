from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.base import Base


APP_DATA_DIR = Path.home() / ".nsfw_cutter"
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_PATH = APP_DATA_DIR / "nsfw_cutter.db"

DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

engine = create_engine(
    DATABASE_URL,
    echo=False,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
)


def init_database():
    Base.metadata.create_all(bind=engine)


def get_session():
    return SessionLocal()