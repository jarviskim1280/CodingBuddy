from buddy.db.models import Base, engine

def init_db():
    Base.metadata.create_all(bind=engine)
