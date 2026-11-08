from sqlmodel import create_engine

from app.core.config import settings

engine = create_engine(
    str(settings.SQLALCHEMY_DATABASE_URI),
    pool_pre_ping=True,
    pool_recycle=1800,
    **(
        {"connect_args": {"init_command": "SET time_zone = '+00:00'"}}
        if settings.DATABASE_TYPE == "mysql"
        else {}
    ),
)
