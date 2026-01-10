import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, inspect, text
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta, timezone # Consolidated import
import re
from typing import List, Optional
from urllib.parse import urljoin
from dateutil.parser import parse # Import for robust datetime parsing
import pytz # Import pytz for timezone handling

# Database Configuration
DATABASE_URL = "sqlite:///./chatlog.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# SQLAlchemy Models
class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime)
    username = Column(String, index=True)
    message_html = Column(String)
    channel = Column(String, default="trade")

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
    timestamp = Column(DateTime)
    read = Column(Boolean, default=False)
    is_hidden = Column(Boolean, default=False) # New column

# Pydantic Models
class MessageCreate(BaseModel):
    timestamp: datetime
    username: str
    message_html: str
    channel: str

class MessageModel(MessageCreate):
    id: int

    class Config:
        from_attributes = True

class MentionModel(BaseModel):
    id: int
    message_id: int
    mentioned_user: str
    message_html: str
    timestamp: datetime
    read: bool
    is_hidden: bool # New field

    class Config:
        from_attributes = True

class ConfigModel(BaseModel):
    key: str
    value: str

# FastAPI App
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

def parse_chat_log():
    db = SessionLocal()
    channel_to_parse = get_config(db, "channel", "trade")
    BASE_URL = "http://farmrpg.com/"
    URL = f"{BASE_URL}chatlog.php?channel={channel_to_parse}"
    
    try:
        page = requests.get(URL)
        soup = BeautifulSoup(page.content, "html.parser")
        
        chat_lines = soup.find_all("li", class_="item-content")
        
        for line in reversed(chat_lines):
            title = line.find("div", class_="item-title")
            if not title:
                continue

            for a_tag in title.find_all('a'):
                if a_tag.has_attr('href'):
                    a_tag['href'] = urljoin(BASE_URL, a_tag['href'])
            for img_tag in title.find_all('img'):
                if img_tag.has_attr('src'):
                    img_tag['src'] = urljoin(BASE_URL, img_tag['src'])

            timestamp_str = title.find("strong").text if title.find("strong") else None
            # Find the user link by looking for the specific profile URL structure
            user_anchor = title.find("a", href=re.compile(r"profile\.php\?user_name="))
            username = user_anchor.text if user_anchor else "System"
            
            if timestamp_str:
                try:
                    full_timestamp_str = f"{timestamp_str} {datetime.now().year}" # Use datetime.now()
                    # Parse using dateutil, then localize to America/Chicago
                    naive_timestamp = parse(full_timestamp_str)
                    timestamp = chicago_tz.localize(naive_timestamp, is_dst=None) # Store as Chicago-aware
                except ValueError:
                    continue

                original_title_html = str(title)
                message_text_for_mention_check = title.get_text()

                if title.strong:
                    title.strong.decompose()
                if title.find("br"):
                    title.find("br").decompose()
                
                message_content_html = str(title)

                existing_message = db.query(Message).filter_by(timestamp=timestamp, username=username).first()
                if not existing_message:
                    new_message = Message(
                        timestamp=timestamp,
                        username=username,
                        message_html=message_content_html,
                        channel=channel_to_parse
                    )
                    db.add(new_message)
                    db.flush()

                    # Find all mentioned users in the message text
                    mentioned_users = re.findall(r'@(\w+)', message_text_for_mention_check)
                    for mentioned_user in mentioned_users:
                        existing_mention = db.query(Mention).filter_by(message_id=new_message.id, mentioned_user=mentioned_user).first()
                        if not existing_mention:
                            new_mention = Mention(
                                message_id=new_message.id,
                                mentioned_user=mentioned_user,
                                message_html=message_content_html,
                                timestamp=timestamp,
                                read=False,
                                is_hidden=False
                            )
                            db.add(new_mention)
        
        db.commit()
        print(f"Chat log parsed successfully at {datetime.now()}") # Use datetime.now()
    except Exception as e:
        db.rollback()
        print(f"Error parsing chat log: {e}")
    finally:
        db.close()

@app.on_event("startup")
def startup_event():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    if not get_config(db, "channel"):
        set_config(db, "channel", "trade")
    db.close()

    # Manual migration for 'is_hidden' column
    with engine.connect() as connection:
        inspector = inspect(engine)
        if inspector.has_table("mentions"):
            columns = inspector.get_columns('mentions')
            column_names = [col['name'] for col in columns]
            if 'is_hidden' not in column_names:
                with connection.begin():
                    connection.execute(text("ALTER TABLE mentions ADD COLUMN is_hidden BOOLEAN DEFAULT FALSE"))
                print("Added 'is_hidden' column to 'mentions' table.")


    scheduler = BackgroundScheduler()
    # Schedule to run every 30 seconds
    scheduler.add_job(parse_chat_log, 'interval', seconds=3)
    # Schedule to run once immediately
    scheduler.add_job(parse_chat_log, 'date', run_date=datetime.now() + timedelta(seconds=1)) # Use datetime.now() and timedelta
    scheduler.start()

@app.get("/api/messages", response_model=List[MessageModel])
def get_messages(db: Session = Depends(get_db), limit: int = 200, channel: str = "trade"):
    messages = db.query(Message).filter(Message.channel == channel).order_by(Message.timestamp.desc()).limit(limit).all()
    return messages

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

@app.post("/api/config", response_model=ConfigModel)
def update_channel_config(key: str, value: str, db: Session = Depends(get_db)):
    if key not in ["channel"]:
        raise HTTPException(status_code=400, detail=f"Configuration for '{key}' cannot be set via this endpoint.")
    set_config(db, key, value)
    return ConfigModel(key=key, value=value)

@app.get("/")
def read_root():
    return {"status": "FRPG Chat Logger is running"}