import os
import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import pytz
import requests
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from models import DiscordUser, PersistentSession, get_db, Config, db_write_lock

# --- Environment and Encryption Setup ---
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    raise RuntimeError("ENCRYPTION_KEY environment variable not set. Generate one using: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
fernet = Fernet(ENCRYPTION_KEY.encode())

def encrypt(data: str) -> str:
    return fernet.encrypt(data.encode()).decode()

def decrypt(token: str) -> str:
    return fernet.decrypt(token.encode()).decode()

SESSION_COOKIE_NAME = "frpg_chatterbot_session"

# Define Chicago timezone
chicago_tz = pytz.timezone('America/Chicago')

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
        print("---""DEV MODE: Bypassing authentication. Returning mock user.""---")
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
