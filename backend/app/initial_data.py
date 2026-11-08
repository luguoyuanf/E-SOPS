import logging

from sqlmodel import Session

from app.core.database import engine
from app.platform.bootstrap import init_db
from app.platform.tenant_uow import PlatformGlobalUnitOfWork

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init() -> None:
    with Session(engine) as session:
        # Trusted local provisioning command; never exposed as a request entry.
        with PlatformGlobalUnitOfWork(session):
            init_db(session)


def main() -> None:
    logger.info("Creating initial data")
    init()
    logger.info("Initial data created")


if __name__ == "__main__":
    main()
