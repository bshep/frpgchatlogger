import re
import asyncio
import requests
from bs4 import BeautifulSoup
import urllib.parse
from typing import Dict, Any
from sqlalchemy.orm import Session

from mailbox_db import UserMailbox

# --- Cache for MBOXID (in-memory for speed) ---
mboxid_cache: Dict[str, str] = {}

# --- FarmRPG Cookies ---
cookies = {
    'farmrpg_token': 'ms4va20ulqi5eqi3d3u8cd0fjdq510patjg81ibn',
    'HighwindFRPG': 'jpsauB751C4suBlUfV%2B9x%2F0JiYSOhMFIongLB%2BNjT9k%3D%3Cstrip%3E%24argon2id%24v%3D19%24m%3D7168%2Ct%3D4%2Cp%3D1%24UmJQdHdKeXNTN3dEL0lOTw%24PI3%2FFhpSH1WuoYzXBivw2DWHChpYsUdwCWCJcBtLgLU',
    'pac_ocean': '43F8CA30'
}

async def get_mboxid(db: Session, username: str) -> str:
    """
    Gets the MBOXID for a user, using a multi-level cache (in-memory and DB).
    """
    # 1. Check in-memory cache
    if username in mboxid_cache:
        return mboxid_cache[username]

    # 2. Check database cache
    db_entry = db.query(UserMailbox).filter(UserMailbox.username == username).first()
    if db_entry:
        mboxid_cache[username] = db_entry.mboxid  # Populate in-memory cache
        return db_entry.mboxid

    # 3. Fetch from web
    encoded_username = urllib.parse.quote(username)
    profile_url = f"https://farmrpg.com/profile.php?user_name={encoded_username}"

    try:
        response = await asyncio.to_thread(requests.get, profile_url, cookies=cookies, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        
        link = soup.find("a", href=re.compile(r"mailbox\.php\?id=\d+"))
        if not link or not link.get('href'):
            raise ValueError(f"Mailbox ID not found for user '{username}'.")
        
        mboxid_match = re.search(r"id=(\d+)", link['href'])
        if not mboxid_match:
            raise ValueError(f"Could not parse Mailbox ID for user '{username}'.")
            
        mboxid = mboxid_match.group(1)
        
        # 4. Save to caches
        mboxid_cache[username] = mboxid
        new_db_entry = UserMailbox(username=username, mboxid=mboxid)
        db.add(new_db_entry)
        db.commit() # Commit immediately to ensure it's saved

        return mboxid
    except requests.RequestException as e:
        raise ConnectionError(f"Failed to fetch profile page for user '{username}': {e}")


async def poll_user_mailbox(db: Session, username: str) -> Dict[str, Any]:
    """Polls a single user's mailbox and returns structured data."""
    if not username:
        return {"username": username, "status": "error", "message": "Empty username provided."}

    try:
        mboxid = await get_mboxid(db, username)
        mailbox_url = f"https://farmrpg.com/mailbox.php?id={mboxid}"
        
        response = await asyncio.to_thread(requests.get, mailbox_url, cookies=cookies, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        
        status_span = soup.find("span", id=re.compile(r"\d+-inmailbox"))
        if not status_span:
            raise ValueError(f"Could not find item count for user '{username}'.")
            
        parts = status_span.parent.text.split('/')
        if len(parts) != 2:
            raise ValueError(f"Could not parse item count for user '{username}'.")
            
        current_items = int(parts[0].strip().replace(',', ''))
        max_items = int(parts[1].strip().replace(',', ''))
        fill_ratio = current_items / max_items if max_items > 0 else 0
        
        is_open = (max_items - current_items > 100) or (max_items > 0 and current_items / max_items <= 0.5)
        
        if not is_open:
            color = "RED"
        else:
            if fill_ratio <= 0.1:
                color = "GREEN"
            else:
                color = "YELLOW"
                
        return {
            "username": username,
            "status": color,
            "current_items": current_items,
            "max_items": max_items,
            "fill_ratio": round(fill_ratio, 3) if max_items > 0 else 0,
            "error": None
        }
        
    except Exception as e:
        db.rollback() # Rollback any potential db changes from get_mboxid if polling fails
        return {"username": username, "status": "error", "error": str(e)}

