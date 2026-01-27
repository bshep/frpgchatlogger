import os
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime

DATABASE_URL = "sqlite:///./mailbox.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

from sqlalchemy.schema import UniqueConstraint

class UserMonitoringPreference(Base):
    __tablename__ = "user_monitoring_preferences"
    id = Column(Integer, primary_key=True, index=True)
    discord_user_id = Column(String, nullable=False, index=True)
    username = Column(String, nullable=False, index=True)

    __table_args__ = (UniqueConstraint('discord_user_id', 'username', name='_discord_user_username_uc'),)

class UserMailbox(Base):
    __tablename__ = "user_mailbox"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    mboxid = Column(String, nullable=False)

class MailboxStatus(Base):
    __tablename__ = "mailbox_status"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    status = Column(String, nullable=False)
    current_items = Column(Integer, nullable=False)
    max_items = Column(Integer, nullable=False)
    fill_ratio = Column(Float, nullable=False)
    last_updated = Column(DateTime, nullable=False, default=datetime.utcnow)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_db_and_tables():
    # This check prevents creating tables if they already exist
    if not os.path.exists(DATABASE_URL.replace("sqlite:///", "")):
        print("Creating mailbox database and tables...")
        Base.metadata.create_all(bind=engine)
        print("Mailbox database and tables created.")
    else:
        # Still make sure tables are created if the db file exists but is empty/corrupt
        Base.metadata.create_all(bind=engine)

# To be called on application startup
create_db_and_tables()
