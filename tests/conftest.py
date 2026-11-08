from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.db import init_db


def make_session():
    engine = create_engine("sqlite://")
    init_db(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory()
