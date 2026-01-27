from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from mailbox_db import SessionLocal, UserMonitoringPreference, MailboxStatus
from schemas import UsernamesPayload
from dependencies import get_current_user
from models import DiscordUser

router = APIRouter()

def get_mailbox_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/api/mailbox/preferences", summary="Set the list of users to be monitored by the current user")
def set_user_mailbox_preferences(
    payload: UsernamesPayload, 
    current_user: DiscordUser = Depends(get_current_user),
    db: Session = Depends(get_mailbox_db)
):
    """
    Sets the mailbox monitoring preferences for the authenticated Discord user.
    The scheduler will pick up all unique usernames from all users for polling.
    """
    discord_user_id = current_user.id
    
    unique_usernames = sorted(list(set(u for u in payload.usernames if u.strip())))
    if len(unique_usernames) > 5:
        raise HTTPException(status_code=400, detail="You can only monitor up to 5 users.")
            
    try:
        # Delete existing preferences for this user
        db.query(UserMonitoringPreference).filter(UserMonitoringPreference.discord_user_id == discord_user_id).delete()
        
        # Add new preferences
        for username in unique_usernames:
            db.add(UserMonitoringPreference(discord_user_id=discord_user_id, username=username))
            
        db.commit()
        return {"message": f"Successfully updated monitoring preferences for {current_user.username}.", "usernames": unique_usernames}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"An error occurred: {e}")

@router.get("/api/mailbox/preferences", summary="Get the list of users monitored by the current user")
def get_user_mailbox_preferences(
    current_user: DiscordUser = Depends(get_current_user),
    db: Session = Depends(get_mailbox_db)
):
    """
    Returns the list of usernames that the authenticated Discord user is monitoring.
    """
    discord_user_id = current_user.id
    preferences = db.query(UserMonitoringPreference).filter(UserMonitoringPreference.discord_user_id == discord_user_id).order_by(UserMonitoringPreference.username).all()
    return {"usernames": [p.username for p in preferences]}


@router.get("/api/mailbox-status", summary="Get latest stored Mailbox Status for all relevant users")
def get_all_mailbox_statuses(db: Session = Depends(get_mailbox_db)):
    """
    Retrieves the latest mailbox status for all unique users that ANY site user is monitoring from the database.
    The data is updated by the background scheduler.
    """
    statuses = db.query(MailboxStatus).all()
    
    # Return a dictionary keyed by username for easy lookup on the frontend
    return {status.username: {
        "username": status.username,
        "status": status.status,
        "current_items": status.current_items,
        "max_items": status.max_items,
        "fill_ratio": status.fill_ratio,
        "last_updated": status.last_updated.isoformat()
    } for status in statuses}
