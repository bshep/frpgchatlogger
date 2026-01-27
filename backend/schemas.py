from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

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

class ConfigUpdateRequest(BaseModel):
    configs: List[ConfigModel]

class AnalysisRequest(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None

class UsernamesPayload(BaseModel):
    usernames: List[str]
