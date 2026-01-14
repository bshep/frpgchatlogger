import os
import json
import re
import secrets
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
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import Boolean, Column, DateTime, Integer, String, create_engine, inspect, text 
from sqlalchemy.orm import Session, declarative_base, sessionmaker

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
    class Config: from_attributes = True

class MentionModel(BaseModel):
    id: int
    message_id: int
    mentioned_user: str
    message_html: str
    timestamp: datetime
    read: bool
    is_hidden: bool
    channel: str
    class Config: from_attributes = True

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
    config_item = db.query(Config).filter(Config.key == key).first()
    if config_item:
        config_item.value = value
    else:
        db.add(Config(key=key, value=value))
    db.commit()

# Define Chicago timezone
chicago_tz = pytz.timezone('America/Chicago')

# --- Background Tasks ---
from sqlalchemy import Boolean, Column, DateTime, Integer, String, create_engine, inspect, text, tuple_
from sqlalchemy.orm import Session, declarative_base, sessionmaker

# ... (imports) ...

def parse_single_channel_log(db: Session, channel_to_parse: str):
    """Parses the chat log for a single specified channel using a batch approach."""
    BASE_URL = "http://farmrpg.com/"
    URL = f"{BASE_URL}chatlog.php?channel={channel_to_parse}"
    
    try:
        page = requests.get(URL)
        soup = BeautifulSoup(page.content, "html.parser")
        chat_lines = soup.find_all("li", class_="item-content")

        potential_messages = []
        for line in reversed(chat_lines):
            title = line.find("div", class_="item-title")
            if not title:
                continue

            timestamp_str = title.find("strong").text if title.find("strong") else None
            user_anchor = title.find("a", href=re.compile(r"profile\.php\?user_name="))
            username = user_anchor.text if user_anchor else "System"

            if timestamp_str:
                try:
                    full_timestamp_str = f"{timestamp_str} {datetime.now().year}"
                    naive_timestamp = parse(full_timestamp_str)
                    timestamp = chicago_tz.localize(naive_timestamp, is_dst=None)
                    
                    # Prepare data but don't query DB yet
                    potential_messages.append({
                        "timestamp": timestamp,
                        "username": username,
                        "title_element": title
                    })
                except ValueError:
                    continue
        
        if not potential_messages:
            print(f"No new message formats found for channel '{channel_to_parse}'.")
            return

        # Create a set of unique identifiers for the potential messages
        potential_ids = {(msg["timestamp"], msg["username"]) for msg in potential_messages}

        # Perform one query to get all existing messages that match our potential new ones
        existing_messages = db.query(Message.timestamp, Message.username).filter(
            Message.channel == channel_to_parse,
            tuple_(Message.timestamp, Message.username).in_(potential_ids)
        ).all()
        existing_ids = set(existing_messages)

        # Process only the messages that are actually new
        new_messages_to_add = []
        for msg_data in potential_messages:
            if (msg_data["timestamp"], msg_data["username"]) not in existing_ids:
                new_messages_to_add.append(msg_data)

        if not new_messages_to_add:
            print(f"No new messages to insert for channel '{channel_to_parse}'.")
            return

        for new_msg_data in new_messages_to_add:
            title = new_msg_data["title_element"]
            
            # Reprocess HTML content since it was modified in the first loop
            for a_tag in title.find_all('a'):
                if a_tag.has_attr('href'):
                    a_tag['href'] = urljoin(BASE_URL, a_tag['href'])
            for img_tag in title.find_all('img'):
                if img_tag.has_attr('src'):
                    img_tag['src'] = urljoin(BASE_URL, img_tag['src'])

            message_text_for_mention_check = title.get_text()
            if title.strong: title.strong.decompose()
            if title.find("br"): title.find("br").decompose()
            message_content_html = str(title)

            new_message = Message(
                timestamp=new_msg_data["timestamp"],
                username=new_msg_data["username"],
                message_html=message_content_html,
                channel=channel_to_parse
            )
            db.add(new_message)
            # We must flush to get the ID for the mention's foreign key
            db.flush() 

            mentioned_users = re.findall(r'@(\w+)', message_text_for_mention_check)
            for mentioned_user in mentioned_users:
                # This part is still N+1, but will only run for truly new messages with mentions.
                # A more complex solution could batch this as well, but this is a major improvement.
                existing_mention = db.query(Mention).filter_by(message_id=new_message.id, mentioned_user=mentioned_user).first()
                if not existing_mention:
                    db.add(Mention(
                        message_id=new_message.id,
                        mentioned_user=mentioned_user,
                        message_html=message_content_html,
                        timestamp=new_msg_data["timestamp"],
                        read=False,
                        is_hidden=False,
                        channel=channel_to_parse
                    ))
        
        db.commit()
        print(f"Processed {len(new_messages_to_add)} new messages for channel '{channel_to_parse}' successfully at {datetime.now()}")
    except Exception as e:
        db.rollback()
        print(f"Error parsing chat log for channel '{channel_to_parse}': {e}")


def scheduled_log_parsing():
    """Scheduled task to parse logs for all configured channels."""
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

def cleanup_expired_persistent_sessions():
    """Scheduled job to delete expired persistent user sessions from the database."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        expired_count = db.query(PersistentSession).filter(PersistentSession.expiry_date <= now).delete()
        if expired_count > 0:
            db.commit()
            print(f"Cleaned up {expired_count} expired persistent user sessions.")
    except Exception as e:
        print(f"Error during expired persistent session cleanup: {e}")
        db.rollback()
    finally:
        db.close()

def run_migrations(engine):
    """
    Checks for and creates missing indexes on existing tables.
    This serves as a simple migration helper.
    """
    print("Running database migrations for indexes...")
    inspector = inspect(engine)
    
    # --- Indexes for 'messages' table ---
    try:
        message_indexes = [index['name'] for index in inspector.get_indexes('messages')]
        if 'ix_messages_timestamp' not in message_indexes:
            with engine.connect() as connection:
                with connection.begin():
                    connection.execute(text('CREATE INDEX ix_messages_timestamp ON messages (timestamp)'))
            print("Created index: ix_messages_timestamp")
        if 'ix_messages_channel' not in message_indexes:
            with engine.connect() as connection:
                with connection.begin():
                    connection.execute(text('CREATE INDEX ix_messages_channel ON messages (channel)'))
            print("Created index: ix_messages_channel")
    except Exception as e:
        print(f"Could not create indexes for 'messages' table (may not exist yet): {e}")

    # --- Indexes for 'mentions' table ---
    try:
        mention_indexes = [index['name'] for index in inspector.get_indexes('mentions')]
        if 'ix_mentions_timestamp' not in mention_indexes:
            with engine.connect() as connection:
                with connection.begin():
                    connection.execute(text('CREATE INDEX ix_mentions_timestamp ON mentions (timestamp)'))
            print("Created index: ix_mentions_timestamp")
    except Exception as e:
        print(f"Could not create indexes for 'mentions' table (may not exist yet): {e}")

    # --- Indexes for 'persistent_sessions' table ---
    try:
        session_indexes = [index['name'] for index in inspector.get_indexes('persistent_sessions')]
        if 'ix_persistent_sessions_expiry_date' not in session_indexes:
            with engine.connect() as connection:
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
    # Set default channels to track if not already configured
    if not get_config(db, "channels_to_track"):
        set_config(db, "channels_to_track", "trade,giveaways")
    # Set default allowed lists if not already configured
    if not get_config(db, "allowed_users"):
        set_config(db, "allowed_users", "")
    if not get_config(db, "allowed_guilds"):
        set_config(db, "allowed_guilds", "")
    db.close()

    scheduler = BackgroundScheduler()
    # Schedule to run every 3 seconds
    scheduler.add_job(scheduled_log_parsing, 'interval', seconds=5)
    scheduler.add_job(cleanup_expired_persistent_sessions, 'interval', hours=1)
    # Schedule to run once immediately
    scheduler.add_job(scheduled_log_parsing, 'date', run_date=datetime.now() + timedelta(seconds=1))
    scheduler.start()

# --- Authentication / Authorization Helpers ---
def is_user_allowed(user: DiscordUser, db: Session) -> bool:
    """Checks if a user is in the allowed users list or in an allowed guild."""
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

async def get_current_user_optional(request: Request, db: Session = Depends(get_db)) -> Optional[DiscordUser]:
    """Dependency to get the current user if a valid session exists, otherwise returns None."""
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
    
    query = db.query(Message)
    
    # Perform a case-insensitive search on the message content.
    query = query.filter(Message.message_html.ilike(f"%{q}%"))
    
    if channel:
        query = query.filter(Message.channel == channel)
        
    # Return results ordered by most recent first, with a safety limit.
    results = query.order_by(Message.timestamp.desc()).limit(500).all()
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
    mention = db.query(Mention).filter(Mention.id == mention_id).first()
    if not mention:
        raise HTTPException(status_code=404, detail="Mention not found")
    
    mention.is_hidden = True # Set to hidden instead of deleting
    db.commit()
    return {"message": "Mention hidden successfully"}

@app.get("/api/config", response_model=List[ConfigModel])
def get_all_configs(db: Session = Depends(get_db)):
    return db.query(Config).all()

# Turned off to prevent unauthorized config changes, eventually can implement auth.
# @app.post("/api/config", response_model=ConfigModel)
# def update_channel_config(key: str, value: str, db: Session = Depends(get_db)):
#     # Allow 'channels_to_track' to be configured via the API.
#     if key not in ["channels_to_track"]:

# --- Authentication / Authorization Helpers ---
def is_user_allowed(user: DiscordUser, db: Session) -> bool:
    """Checks if a user is in the allowed users list or in an allowed guild."""
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



# --- API Endpoints ---
@app.get("/")
def read_root():
    return {"status": "FRPG Chat Logger is running"}

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
    return AuthStatusModel(
        username=f"{current_user.username}#{current_user.discriminator}",
        is_allowed=allowed
    )

@app.post("/api/logout")
async def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if session_token:
        # Delete the session from the database
        db.query(PersistentSession).filter(PersistentSession.session_token == session_token).delete()
        db.commit()
    
    # Instruct the browser to delete the cookie
    response.delete_cookie(key=SESSION_COOKIE_NAME)
    return {"message": "Logout successful"}
