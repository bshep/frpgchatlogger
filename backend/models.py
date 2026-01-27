import os
import threading
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, inspect, text, func
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime, timezone
import pytz

# --- Threading Lock for Database Writes ---
db_write_lock = threading.Lock()

# --- Database Configuration ---
DATABASE_URL = "sqlite:///./chatlog.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- SQLAlchemy Models ---
class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, index=True)
    username = Column(String, index=True)
    message_html = Column(String)
    channel = Column(String, default="trade", index=True)

class MessageArchive(Base):
    __tablename__ = "messages_archive"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, index=True)
    username = Column(String, index=True)
    message_html = Column(String)
    channel = Column(String, index=True)

class Config(Base):
    __tablename__ = "config"
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True)
    value = Column(String)

class Mention(Base):
    __tablename__ = "mentions"
    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, index=True)
    mentioned_user = Column(String, index=True)
    message_html = Column(String)
    timestamp = Column(DateTime, index=True)
    read = Column(Boolean, default=False)
    is_hidden = Column(Boolean, default=False)
    channel = Column(String, default="trade")

class DiscordUser(Base):
    __tablename__ = "discord_users"
    id = Column(String, primary_key=True, index=True) # Discord User ID
    username = Column(String, nullable=False)
    discriminator = Column(String, nullable=False)
    avatar = Column(String, nullable=True)
    encrypted_access_token = Column(String, nullable=False)
    encrypted_refresh_token = Column(String, nullable=False)
    token_expiry = Column(DateTime, nullable=False)
    guilds_data = Column(String) # Store as JSON string

class PersistentSession(Base):
    __tablename__ = "persistent_sessions"
    id = Column(Integer, primary_key=True, index=True)
    session_token = Column(String, unique=True, index=True, nullable=False)
    discord_id = Column(String, index=True, nullable=False)
    expiry_date = Column(DateTime, nullable=False, index=True)

# --- Database Dependency ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
