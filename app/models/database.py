from __future__ import annotations

import os
import time
from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Text,
    Boolean,
    JSON,
    create_engine,
    DateTime,
)
from sqlalchemy.orm import declarative_base, sessionmaker

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "clipfetch.db")

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class DownloadedVideoInfo(Base):
    """Mirrors com.junkfood.seal.database.objects.DownloadedVideoInfo"""

    __tablename__ = "downloaded_videos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    video_title = Column(String(500), default="")
    video_author = Column(String(200), default="")
    video_url = Column(Text, default="")
    thumbnail_url = Column(Text, default="")
    video_path = Column(Text, default="")
    extractor = Column(String(100), default="")
    file_size = Column(Float, default=0.0)
    duration = Column(Integer, default=0)
    format_info = Column(String(200), default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class CommandTemplate(Base):
    """Mirrors com.junkfood.seal.database.objects.CommandTemplate"""

    __tablename__ = "command_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    template = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class CookieProfile(Base):
    """Mirrors com.junkfood.seal.database.objects.CookieProfile"""

    __tablename__ = "cookie_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    cookies_file = Column(Text, default="")
    user_agent = Column(String(500), default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class OptionShortcut(Base):
    """Mirrors com.junkfood.seal.database.objects.OptionShortcut"""

    __tablename__ = "option_shortcuts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    options = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    Base.metadata.create_all(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
