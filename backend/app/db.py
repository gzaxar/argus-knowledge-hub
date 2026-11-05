import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=20, max_overflow=20)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    from app.services.infn_mail import track_request
    track_request(db)
    try:
        yield db
    finally:
        try:
            from app.services.infn_mail import deliver_request
            deliver_request(db)
        except Exception:
            # The operation is already committed; mail failure must not turn it into an API failure.
            import logging
            logging.getLogger("argus.notify").error("Request mail delivery failed; notifications remain pending")
        finally:
            db.close()
