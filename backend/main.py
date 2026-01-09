import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from apscheduler.schedulers.background import BackgroundScheduler
import datetime
import re
from typing import List, Optional
from urllib.parse import urljoin

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

# Pydantic Models
class MessageCreate(BaseModel):
    timestamp: datetime.datetime
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
    timestamp: datetime.datetime
    read: bool

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
            user_anchor = title.find("a", class_=lambda x: x and x.startswith('cc'))
            username = user_anchor.text if user_anchor else "System"
            
            if timestamp_str:
                try:
                    full_timestamp_str = f"{timestamp_str} {datetime.datetime.now().year}"
                    timestamp = datetime.datetime.strptime(full_timestamp_str, "%b %d, %I:%M:%S %p %Y")
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
                                read=False
                            )
                            db.add(new_mention)
        
        db.commit()
        print(f"Chat log parsed successfully at {datetime.datetime.now()}")
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

    scheduler = BackgroundScheduler()
    scheduler.add_job(parse_chat_log, 'interval', seconds=30)
    scheduler.start()
    parse_chat_log()

@app.get("/api/messages", response_model=List[MessageModel])
def get_messages(db: Session = Depends(get_db), limit: int = 200, channel: str = "trade"):
    messages = db.query(Message).filter(Message.channel == channel).order_by(Message.timestamp.desc()).limit(limit).all()
    return messages

@app.get("/api/mentions", response_model=List[MentionModel])
def get_mentions(username: str, db: Session = Depends(get_db)):
    if not username:
        raise HTTPException(status_code=400, detail="Username parameter is required.")
    mentions = db.query(Mention).filter(Mention.mentioned_user.ilike(username)).order_by(Mention.timestamp.desc()).all()
    return mentions

@app.delete("/api/mentions")
def clear_mentions(username: str, db: Session = Depends(get_db)):
    if not username:
        raise HTTPException(status_code=400, detail="Username parameter is required.")
    db.query(Mention).filter(Mention.mentioned_user.ilike(username)).delete()
    db.commit()
    return {"message": "Mentions cleared successfully"}

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