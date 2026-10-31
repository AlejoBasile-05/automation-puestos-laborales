"""Sesión de base de datos SQLAlchemy."""

from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from jobradar.db.models import Base


def get_engine(db_path: str = "data/jobradar.sqlite") -> "Engine":
    """Crea el engine de SQLAlchemy."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{db_path}", echo=False)


def get_session_factory(engine) -> sessionmaker[Session]:
    """Crea la fábrica de sesiones."""
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(engine) -> None:
    """Inicializa la base de datos creando las tablas."""
    Base.metadata.create_all(engine)
