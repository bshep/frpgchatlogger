import os
import json
import re
import secrets
import subprocess
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import urljoin

import pytz
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
from cryptography.fernet import Fernet
from dateutil.parser import parse
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse
from pydantic import BaseModel
from sqlalchemy import Boolean, Column, DateTime, Integer, String, create_engine, inspect, text, union_all, func
from sqlalchemy.orm import Session, declarative_base, sessionmaker

# --- Threading Lock for Database Writes ---
db_write_lock = threading.Lock()

# --- Environment and Encryption Setup ---
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    raise RuntimeError("ENCRYPTION_KEY environment variable not set. Generate one using: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
fernet = Fernet(ENCRYPTION_KEY.encode())

def encrypt(data: str) -> str:
    return fernet.encrypt(data.encode()).decode()

def decrypt(token: str) -> str:
    return fernet.decrypt(token.encode()).decode()

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

# --- Pydantic Models ---
class MessageModel(BaseModel):
    id: int
    timestamp: datetime
    username: str
    message_html: str
    channel: str
    class Config:
        from_attributes = True

class MentionModel(BaseModel):
    id: int
    message_id: int
    mentioned_user: str
    message_html: str
    timestamp: datetime
    read: bool
    is_hidden: bool
    channel: str
    class Config:
        from_attributes = True

class ConfigModel(BaseModel):
    key: str
    value: str

class GuildModel(BaseModel):
    id: str
    name: str
    icon: Optional[str]
    owner: bool
    permissions: str

class UserModel(BaseModel):
    id: str
    username: str
    avatar: Optional[str]
    guilds: List[GuildModel]

class AuthStatusModel(BaseModel):
    username: str
    is_allowed: bool
    is_admin: bool
    is_analysis_allowed: bool

# --- FastAPI App Setup ---
app = FastAPI()

# CORS Middleware
origins = ["http://localhost:5173"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
SESSION_COOKIE_NAME = "frpg_chatterbot_session"

# --- Database Dependency ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_config(db: Session, key: str, default: Optional[str] = None) -> Optional[str]:
    config_item = db.query(Config).filter(Config.key == key).first()
    return config_item.value if config_item else default

def set_config(db: Session, key: str, value: str):
    with db_write_lock:
        config_item = db.query(Config).filter(Config.key == key).first()
        if config_item:
            config_item.value = value
        else:
            db.add(Config(key=key, value=value))
        db.commit()

# Define Chicago timezone
chicago_tz = pytz.timezone('America/Chicago')

# --- Background Tasks ---
def parse_single_channel_log(db: Session, channel_to_parse: str):
    """
    Parses the chat log for a single specified channel.
    It stops parsing after finding a certain number of consecutive messages
    that are already in the database.
    """
    CONSECUTIVE_FOUND_THRESHOLD = 5
    BASE_URL = "http://farmrpg.com/"
    URL = f"{BASE_URL}chatlog.php?channel={channel_to_parse}"

    try:
        page = requests.get(URL, timeout=60)
        soup = BeautifulSoup(page.content, "html.parser")
        chat_lines = soup.find_all("li", class_="item-content")

        consecutive_found_count = 0
        new_messages_count = 0

        # The chat log is newest-to-oldest, so we iterate in that order.
        for line in chat_lines:
            title = line.find("div", class_="item-title")
            if not title:
                continue

            timestamp_str = title.find("strong").text if title.find("strong") else None
            user_anchor = title.find("a", href=re.compile(r"profile.php?user_name="))
            username = user_anchor.text if user_anchor else "System"

            if not timestamp_str:
                continue

            try:
                full_timestamp_str = f"{timestamp_str} {datetime.now().year}"
                naive_timestamp = parse(full_timestamp_str)
                timestamp = chicago_tz.localize(naive_timestamp, is_dst=None)
            except ValueError:
                continue

            # Check for existence using the composite key
            existing_message = db.query(Message).filter_by(timestamp=naive_timestamp, username=username, channel=channel_to_parse).first()

            if existing_message:
                consecutive_found_count += 1
                if consecutive_found_count >= CONSECUTIVE_FOUND_THRESHOLD:
                    print(f"Caught up with logs for channel '{channel_to_parse}'. Found {CONSECUTIVE_FOUND_THRESHOLD} consecutive existing messages.")
                    break
            else:
                # Reset counter and add the new message
                consecutive_found_count = 0
                new_messages_count += 1

                # --- Process and add the new message ---
                for a_tag in title.find_all('a'):
                    if a_tag.has_attr('href'):
                        a_tag['href'] = urljoin(BASE_URL, a_tag['href'])
                for img_tag in title.find_all('img'):
                    if img_tag.has_attr('src'):
                        img_tag['src'] = urljoin(BASE_URL, img_tag['src'])

                message_text_for_mention_check = title.get_text()

                if title.strong:
                    title.strong.decompose()
                if title.find("br"):
                    title.find("br").decompose()

                message_content_html = str(title)

                new_message = Message(
                    timestamp=timestamp,
                    username=username,
                    message_html=message_content_html,
                    channel=channel_to_parse
                )
                db.add(new_message)
                db.flush()  # We need the ID for mentions

                # Find and add mentions
                mentioned_users = re.findall(r'@(\w+)', message_text_for_mention_check)
                for mentioned_user in mentioned_users:
                    db.add(Mention(
                        message_id=new_message.id,
                        mentioned_user=mentioned_user,
                        message_html=message_content_html,
                        timestamp=timestamp,
                        read=False, is_hidden=False, channel=channel_to_parse
                    ))

        if new_messages_count > 0:
            db.commit()
            print(f"Added {new_messages_count} new messages for channel '{channel_to_parse}'.")
        else:
            # No new messages, so no commit needed.
            print(f"No new messages found for channel '{channel_to_parse}'.")

    except Exception as e:
        db.rollback()
        print(f"Error parsing chat log for channel '{channel_to_parse}': {e}")
        import traceback
        traceback.print_exc()

def scheduled_log_parsing():
    """Scheduled task to parse logs for all configured channels."""
    with db_write_lock:
        db = SessionLocal()
        try:
            channels_str = get_config(db, "channels_to_track", "trade,giveaways")
            if channels_str:
                channels = [channel.strip() for channel in channels_str.split(',')]
                for channel in channels:
                    if channel: # Ensure channel string is not empty
                        parse_single_channel_log(db, channel)
        finally:
            db.close()

def archive_old_messages():
    """Scheduled job to move messages older than 2 hours to the archive table."""
    with db_write_lock:
        db = None
        try:
            db = SessionLocal()
            CHUNK_SIZE = 500  # Stay safely below the 999 variable limit for SQLite
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=2)
            total_archived = 0

            while True:
                # Find a chunk of messages to archive
                messages_to_archive = db.query(Message).filter(Message.timestamp < cutoff_time).limit(CHUNK_SIZE).all()

                if not messages_to_archive:
                    break  # No more messages to archive

                # Prepare data for bulk insert
                archive_data = [
                    {
                        "id": msg.id, "timestamp": msg.timestamp, "username": msg.username,
                        "message_html": msg.message_html, "channel": msg.channel,
                    }
                    for msg in messages_to_archive
                ]

                if archive_data:
                    db.bulk_insert_mappings(MessageArchive, archive_data)

                    ids_to_delete = [msg.id for msg in messages_to_archive]
                    db.query(Message).filter(Message.id.in_(ids_to_delete)).delete(synchronize_session=False)

                    db.commit()  # Commit each chunk as a transaction

                    chunk_size = len(messages_to_archive)
                    total_archived += chunk_size
                    print(f"Archived a chunk of {chunk_size} messages...")

            if total_archived > 0:
                print(f"Successfully archived a total of {total_archived} messages.")
            else:
                print("No messages to archive.")

        except Exception as e:
            if db:
                db.rollback()
            print(f"Error during message archiving: {e}")
        finally:
            if db:
                db.close()

def cleanup_expired_persistent_sessions():
    """Scheduled job to delete expired persistent user sessions from the database."""
    with db_write_lock:
        db = None
        try:
            db = SessionLocal()
            now = datetime.now(timezone.utc)
            expired_count = db.query(PersistentSession).filter(PersistentSession.expiry_date <= now).delete()
            if expired_count > 0:
                db.commit()
                print(f"Cleaned up {expired_count} expired persistent user sessions.")
        except Exception as e:
            if db:
                db.rollback()
            print(f"Error during expired persistent session cleanup: {e}")
        finally:
            if db:
                db.close()

def deduplicate_table(db_session, model):
    """
    Finds and deletes duplicate entries in a given table based on
    (timestamp, username, channel) composite key.
    """
    table_name = model.__tablename__
    print(f"Checking for duplicates in '{table_name}' table...")

    # 1. Find groups of rows that are duplicates
    duplicate_groups = db_session.query(
        model.timestamp,
        model.username,
        model.channel,
        func.count(model.id).label('count')
    ).group_by(
        model.timestamp,
        model.username,
        model.channel
    ).having(func.count(model.id) > 1).all()

    total_deleted = 0
    if not duplicate_groups:
        print(f"No duplicates found in '{table_name}'.")
        return

    print(f"Found {len(duplicate_groups)} groups of duplicate messages in '{table_name}'. Processing...")

    # 2. For each group, find all IDs, then delete all but the one with the minimum ID
    for group in duplicate_groups:
        # Get all rows for the current duplicate group, ordered by ID
        all_duplicate_rows = db_session.query(model).filter(
            model.timestamp == group.timestamp,
            model.username == group.username,
            model.channel == group.channel
        ).order_by(model.id).all()

        # The first one in the list is the one we keep; the rest are to be deleted
        rows_to_delete = all_duplicate_rows[1:]

        for row in rows_to_delete:
            db_session.delete(row)

        num_deleted_for_group = len(rows_to_delete)
        total_deleted += num_deleted_for_group
        print(f"  - Deleting {num_deleted_for_group} extra entries for user '{group.username}' at {group.timestamp} in channel '{group.channel}'.")

    # 3. Commit the transaction
    db_session.commit()
    print(f"\nTotal duplicate entries deleted from '{table_name}': {total_deleted}")

def deduplicate_messages():
    """Scheduled task to deduplicate messages in the database."""
    with db_write_lock:
        db = SessionLocal()
        try:
            deduplicate_table(db, Message)
            deduplicate_table(db, MessageArchive)
        finally:
            db.close()


def run_migrations(l_engine):
    """
    Checks for and creates missing indexes on existing tables.
    This serves as a simple migration helper.
    """
    with db_write_lock:
        print("Running database migrations for indexes...")
        inspector = inspect(l_engine)

        # --- Indexes for 'messages' table ---
        try:
            message_indexes = [index['name'] for index in inspector.get_indexes('messages')]
            if 'ix_messages_timestamp' not in message_indexes:
                with l_engine.connect() as connection:
                    with connection.begin():
                        connection.execute(text('CREATE INDEX ix_messages_timestamp ON messages (timestamp)'))
                print("Created index: ix_messages_timestamp")
            if 'ix_messages_channel' not in message_indexes:
                with l_engine.connect() as connection:
                    with connection.begin():
                        connection.execute(text('CREATE INDEX ix_messages_channel ON messages (channel)'))
                print("Created index: ix_messages_channel")
        except Exception as e:
            print(f"Could not create indexes for 'messages' table (may not exist yet): {e}")

        # --- Indexes for 'mentions' table ---
        try:
            mention_indexes = [index['name'] for index in inspector.get_indexes('mentions')]
            if 'ix_mentions_timestamp' not in mention_indexes:
                with l_engine.connect() as connection:
                    with connection.begin():
                        connection.execute(text('CREATE INDEX ix_mentions_timestamp ON mentions (timestamp)'))
                print("Created index: ix_mentions_timestamp")
        except Exception as e:
            print(f"Could not create indexes for 'mentions' table (may not exist yet): {e}")

        # --- Indexes for 'persistent_sessions' table ---
        try:
            session_indexes = [index['name'] for index in inspector.get_indexes('persistent_sessions')]
            if 'ix_persistent_sessions_expiry_date' not in session_indexes:
                with l_engine.connect() as connection:
                    with connection.begin():
                        connection.execute(text('CREATE INDEX ix_persistent_sessions_expiry_date ON persistent_sessions (expiry_date)'))
                print("Created index: ix_persistent_sessions_expiry_date")
        except Exception as e:
            print(f"Could not create indexes for 'persistent_sessions' table (may not exist yet): {e}")

        print("Index migration check complete.")

@app.on_event("startup")
def startup_event():
    Base.metadata.create_all(bind=engine)
    run_migrations(engine) # Run migrations to create indexes if they don't exist

    db = SessionLocal()
    # Set default configs if not already configured
    defaults = {
        "channels_to_track": "trade,giveaways",
        "allowed_users": "",
        "allowed_guilds": "",
        "admin_users": "",
        "scheduler_polling_interval": "5",
        "analysis_chunk_size": "50",
        "conversion_rate_ap_to_gold": "60",
        "conversion_rate_oj_to_gold": "10",
        "conversion_rate_ac_to_gold": "25",
        "analysis_allowed_users": "",
        "analysis_allowed_guilds": ""
    }
    for key, value in defaults.items():
        if not get_config(db, key):
            set_config(db, key, value)
    db.close()

# --- Authentication / Authorization Helpers ---
def is_user_allowed(user: DiscordUser, db: Session) -> bool:
    """Checks if a user is in the allowed users list or in an allowed guild."""
    # --- Dev Mode Auth Bypass ---
    if os.getenv("DEV_MODE_BYPASS_AUTH", "false").lower() == "true":
        return True
    # --- End Dev Mode Auth Bypass ---
    if not user:
        return False

    allowed_users_str = get_config(db, "allowed_users", "")
    allowed_guilds_str = get_config(db, "allowed_guilds", "")
    
    allowed_users = set(u.strip() for u in allowed_users_str.split(',') if u.strip())
    allowed_guilds = set(g.strip() for g in allowed_guilds_str.split(',') if g.strip())

    # 1. Check if user's ID is in the allowed list
    if user.id in allowed_users:
        return True

    # 2. Check if any of the user's guilds are in the allowed list
    user_guilds = json.loads(user.guilds_data)
    user_guild_ids = {guild['id'] for guild in user_guilds}
    if allowed_guilds.intersection(user_guild_ids):
        return True
    
    return False

def is_user_admin(user: DiscordUser, db: Session) -> bool:
    """Checks if a user is in the admin users list."""
    # --- Dev Mode Auth Bypass ---
    if os.getenv("DEV_MODE_BYPASS_AUTH", "false").lower() == "true":
        return True
    # --- End Dev Mode Auth Bypass ---
    if not user:
        return True

    admin_users_str = get_config(db, "admin_users", "")
    admin_users = set(u.strip() for u in admin_users_str.split(',') if u.strip())

    return user.id in admin_users

def is_user_analysis_allowed(user: DiscordUser, db: Session) -> bool:
    """Checks if a user is an admin or in the analysis-specific allow lists."""
    if is_user_admin(user, db):
        return True

    analysis_users_str = get_config(db, "analysis_allowed_users", "")
    analysis_guilds_str = get_config(db, "analysis_allowed_guilds", "")
    
    analysis_users = set(u.strip() for u in analysis_users_str.split(',') if u.strip())
    analysis_guilds = set(g.strip() for g in analysis_guilds_str.split(',') if g.strip())

    if user.id in analysis_users:
        return True

    user_guilds = json.loads(user.guilds_data)
    user_guild_ids = {guild['id'] for guild in user_guilds}
    if analysis_guilds.intersection(user_guild_ids):
        return True
    
    return False

async def get_current_user_optional(request: Request, db: Session = Depends(get_db)) -> Optional[DiscordUser]:
    """Dependency to get the current user if a valid session exists, otherwise returns None."""
    # --- Dev Mode Auth Bypass ---
    if os.getenv("DEV_MODE_BYPASS_AUTH", "false").lower() == "true":
        print("--- DEV MODE: Bypassing authentication. Returning mock user. ---")
        return DiscordUser(
            id="123456789",
            username="DevUser",
            discriminator="0000",
            avatar=None,
            encrypted_access_token="dummy_token",
            encrypted_refresh_token="dummy_token",
            token_expiry=datetime.now(timezone.utc) + timedelta(days=1),
            guilds_data='[]' # No guilds by default
        )
    # --- End Dev Mode Auth Bypass ---
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return None

    session = db.query(PersistentSession).filter(PersistentSession.session_token == session_token).first()
    if not session or session.expiry_date.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
        if session:
            db.delete(session)
            db.commit()
        return None

    user = db.query(DiscordUser).filter(DiscordUser.id == session.discord_id).first()
    if not user:
        return None
    
    return user

async def get_current_user(request: Request, db: Session = Depends(get_db)) -> DiscordUser:
    user = await get_current_user_optional(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

async def get_admin_user(request: Request, db: Session = Depends(get_db)) -> DiscordUser:
    user = await get_current_user(request, db)
    if not is_user_admin(user, db):
        raise HTTPException(status_code=403, detail="You are not authorized to access this page.")
    return user

async def get_analysis_user(request: Request, db: Session = Depends(get_db)) -> DiscordUser:
    user = await get_current_user(request, db)
    if not is_user_analysis_allowed(user, db):
        raise HTTPException(status_code=403, detail="You are not authorized to access this feature.")
    return user

# --- API Endpoints ---

@app.get("/api/messages", response_model=List[MessageModel])
def get_messages(
    db: Session = Depends(get_db), 
    channel: str = "trade",
    current_user: Optional[DiscordUser] = Depends(get_current_user_optional)
):
    # Determine limit based on auth status
    limit = 200 if current_user and is_user_allowed(current_user, db) else 75
    
    messages = db.query(Message).filter(Message.channel == channel).order_by(Message.timestamp.desc()).limit(limit).all()
    return messages

@app.get("/api/search", response_model=List[MessageModel])
def search_messages(
    q: str, 
    channel: Optional[str] = None, 
    db: Session = Depends(get_db),
    current_user: DiscordUser = Depends(get_current_user)
):
    # Ensure the user is allowed to use this feature
    if not is_user_allowed(current_user, db):
        raise HTTPException(status_code=403, detail="You are not authorized to use the search feature.")

    if not q:
        return []

    # Define the filter condition
    q_filter = Message.message_html.ilike(f"%{q}%")
    
    # Query for recent messages
    recent_query = db.query(Message).filter(q_filter)
    if channel:
        recent_query = recent_query.filter(Message.channel == channel)

    # Query for archived messages
    archive_query = db.query(MessageArchive).filter(MessageArchive.message_html.ilike(f"%{q}%"))
    if channel:
        archive_query = archive_query.filter(MessageArchive.channel == channel)
    
    # Combine them
    # Note: Using python union is simpler here than SQL union for combining two lists of model objects
    combined_results = recent_query.all() + archive_query.all()
    
    # Sort the combined list in Python
    # This is less efficient than a DB order_by on a UNION, but simpler to implement
    # and acceptable for a moderate number of results (limited to 500 total).
    combined_results.sort(key=lambda x: x.timestamp, reverse=True)
    
    # Limit the final result set
    results = combined_results[:500]
    
    return results

@app.get("/api/mentions", response_model=List[MentionModel])
def get_mentions(username: str, db: Session = Depends(get_db), since: Optional[datetime] = None):
    if not username:
        raise HTTPException(status_code=400, detail="Username parameter is required.")
    
    query = db.query(Mention).filter(Mention.mentioned_user.ilike(username)).filter(Mention.is_hidden == False) # Filter out hidden mentions
    
    if since:
        # Frontend sends 'since' as UTC. Convert it to America/Chicago for consistent comparison with stored times.
        if since.tzinfo is None: # If naive, assume UTC as per frontend sending
            since = since.replace(tzinfo=timezone.utc)
        since_chicago = since.astimezone(chicago_tz)
        
        query = query.filter(Mention.timestamp > since_chicago)
        
    mentions = query.order_by(Mention.timestamp.desc()).all()
    return mentions

@app.delete("/api/mentions/{mention_id}")
def delete_mention(mention_id: int, db: Session = Depends(get_db)):
    with db_write_lock:
        mention = db.query(Mention).filter(Mention.id == mention_id).first()
        if not mention:
            raise HTTPException(status_code=404, detail="Mention not found")
        
        mention.is_hidden = True # Set to hidden instead of deleting
        db.commit()
        return {"message": "Mention hidden successfully"}

@app.get("/api/config", response_model=List[ConfigModel])
def get_all_configs(db: Session = Depends(get_db)):
    return db.query(Config).all()

class ConfigUpdateRequest(BaseModel):
    configs: List[ConfigModel]

@app.post("/api/config")
def update_config(request: ConfigUpdateRequest, db: Session = Depends(get_db), admin_user: DiscordUser = Depends(get_admin_user)):
    allowed_keys = [
        "allowed_users", "allowed_guilds", "admin_users", 
        "channels_to_track", "scheduler_polling_interval", "analysis_chunk_size",
        "conversion_rate_ap_to_gold", "conversion_rate_oj_to_gold", "conversion_rate_ac_to_gold",
        "analysis_allowed_users", "analysis_allowed_guilds"
    ]
    for config_item in request.configs:
        if config_item.key in allowed_keys:
            set_config(db, config_item.key, config_item.value)
    return {"message": "Configuration updated successfully."}

# --- Analysis Endpoints ---
@app.get("/analysis.html")
async def get_analysis_page(current_user: DiscordUser = Depends(get_analysis_user)):
    return FileResponse("frontend/analysis.html")

class AnalysisRequest(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None

@app.post("/api/trigger-analysis")
async def trigger_analysis(
    request: AnalysisRequest, 
    db: Session = Depends(get_db), 
    admin_user: DiscordUser = Depends(get_admin_user)
):
    """
    Triggers the chat analysis script.
    """
    # For now dont want this available to run from the production server
    return {"message": "This function is currently not enabled"}

    try:
        # Construct the command to run the analysis script
        command = ["python", "../analysis/analysis.py"]
        if request.start_date:
            command.extend(["--start-date", request.start_date])
        if request.end_date:
            command.extend(["--end-date", request.end_date])

        # Run the analysis script
        process = subprocess.run(command, capture_output=True, text=True, check=True)
        print("Analysis script stdout:", process.stdout)
        print("Analysis script stderr:", process.stderr)

        return {"message": "Analysis triggered successfully."}

    except subprocess.CalledProcessError as e:
        print(f"Error running analysis script: {e}")
        print(f"Stderr: {e.stderr}")
        raise HTTPException(status_code=500, detail=f"Error running analysis script: {e.stderr}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

@app.get("/api/get-analysis-results")
async def get_analysis_results(analysis_user: DiscordUser = Depends(get_analysis_user)):
    """
    Retrieves the latest chat analysis results from the database.
    """
    try:
        analysis_db_path = '../chat_analysis.db'
        if not os.path.exists(analysis_db_path):
            return {"trades": [], "transactions": []} # Return empty if db doesn't exist yet

        conn = sqlite3.connect(analysis_db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Fetch trades
        try:
            c.execute("SELECT * FROM trades")
            trades = [dict(row) for row in c.fetchall()]
        except sqlite3.OperationalError:
            trades = []

        # Fetch transactions
        try:
            c.execute("SELECT * FROM transactions")
            transactions = [dict(row) for row in c.fetchall()]
        except sqlite3.OperationalError:
            transactions = []

        conn.close()

        return {"trades": trades, "transactions": transactions}

    except Exception as e:
        print(f"An unexpected error occurred while fetching analysis results: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")


# --- General Endpoints ---
@app.get("/")
def read_root():
    return {"status": "FRPG Chat Logger is running"}

@app.get("/admin.html")
async def get_admin_page(current_user: DiscordUser = Depends(get_admin_user)):
    return FileResponse("frontend/admin.html")

@app.get("/api/discord-callback")
async def discord_callback(request: Request, code: str, db: Session = Depends(get_db)):
    DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
    DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
    REDIRECT_URI = "http://chat.frpgchatterbot.free.nf/api/discord-callback"
    FRONTEND_REDIRECT_URI = "/"

    if not all([DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET]):
        raise HTTPException(status_code=500, detail="Discord client credentials are not configured on the server.")

    # Exchange code for token
    token_url = "https://discord.com/api/oauth2/token"
    token_data = { "client_id": DISCORD_CLIENT_ID, "client_secret": DISCORD_CLIENT_SECRET, "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI }
    token_response = requests.post(token_url, data=token_data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    token_response.raise_for_status()
    token_json = token_response.json()
    
    # Fetch user identity and guilds
    user_url = "https://discord.com/api/v10/users/@me"
    auth_headers = {"Authorization": f"Bearer {token_json['access_token']}"}
    user_response = requests.get(user_url, headers=auth_headers)
    user_response.raise_for_status()
    user_data = user_response.json()
    discord_id = user_data["id"]

    guilds_response = requests.get(f"{user_url}/guilds", headers=auth_headers)
    guilds_response.raise_for_status()
    guilds_data = guilds_response.json()

    with db_write_lock:
        # Create or update user in database
        db_user = db.query(DiscordUser).filter(DiscordUser.id == discord_id).first()
        token_expiry = datetime.now(timezone.utc) + timedelta(seconds=token_json["expires_in"])
        if not db_user:
            db_user = DiscordUser(id=discord_id)
            db.add(db_user)

        db_user.username, db_user.discriminator, db_user.avatar = user_data["username"], user_data["discriminator"], user_data.get("avatar")
        db_user.encrypted_access_token, db_user.encrypted_refresh_token = encrypt(token_json["access_token"]), encrypt(token_json["refresh_token"])
        db_user.token_expiry, db_user.guilds_data = token_expiry, json.dumps(guilds_data)
        
        # Create long-lived session
        session_token = secrets.token_hex(32)
        session_expiry = datetime.now(timezone.utc) + timedelta(days=180) # ~6 months
        new_session = PersistentSession(session_token=session_token, discord_id=discord_id, expiry_date=session_expiry)
        db.add(new_session)
        db.commit()

    response = RedirectResponse(url=FRONTEND_REDIRECT_URI)
    
    # Set the secure flag based on the request's scheme.
    # FastAPI correctly handles X-Forwarded-Proto headers from reverse proxies.
    secure_cookie = request.url.scheme == "https"

    response.set_cookie(
        key=SESSION_COOKIE_NAME, 
        value=session_token, 
        expires=session_expiry, 
        httponly=True, 
        samesite="Lax", 
        secure=secure_cookie
    )
    return response

@app.get("/api/me", response_model=AuthStatusModel)
async def get_me(current_user: DiscordUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Checks if the currently logged-in user is authorized and returns their status.
    """
    allowed = is_user_allowed(current_user, db)
    admin = is_user_admin(current_user, db)
    analysis_allowed = is_user_analysis_allowed(current_user, db)
    
    return AuthStatusModel(
        username=f"{current_user.username}#{current_user.discriminator}",
        is_allowed=allowed,
        is_admin=admin,
        is_analysis_allowed=analysis_allowed
    )

@app.post("/api/logout")
async def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if session_token:
        with db_write_lock:
            # Delete the session from the database
            db.query(PersistentSession).filter(PersistentSession.session_token == session_token).delete()
            db.commit()
    
    # Instruct the browser to delete the cookie
    response.delete_cookie(key=SESSION_COOKIE_NAME)
    return {"message": "Logout successful"}