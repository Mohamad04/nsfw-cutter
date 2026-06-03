from database.session import SessionLocal, engine, get_db_session, get_session


def init_db():
    from database.init_db import init_db as initialize

    return initialize()


def init_database():
    from database.init_db import init_database as initialize

    return initialize()

__all__ = [
    "SessionLocal",
    "engine",
    "get_db_session",
    "get_session",
    "init_database",
    "init_db",
]
