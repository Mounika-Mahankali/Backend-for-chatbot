from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

engine = create_engine("sqlite:///chatbot.db") #connect db 
Base = declarative_base() #creates tables using classes
SessionLocal = sessionmaker(bind=engine) #connect db in app

# Add new column for chat session PDF path, if missing (supports existing DB)
with engine.connect() as conn:
    try:
        conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN pdf_path STRING"))
    except OperationalError:
        pass
    
    # Add new column for vector DB tracking
    try:
        conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN has_embeddings BOOLEAN DEFAULT 0"))
    except OperationalError:
        pass
    
    try:
        conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN embeddings_updated_at DATETIME"))
    except OperationalError:
        pass

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True)
    password = Column(String)

class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    title = Column(String)
    summary = Column(Text)
    pdf_path = Column(String, nullable=True)
    has_embeddings = Column(Integer, default=0)  # 1 if vector index exists, 0 otherwise
    embeddings_updated_at = Column(DateTime, nullable=True)  # When embeddings were last updated

class Chat(Base):
    __tablename__ = "chats"
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer)
    message = Column(Text)
    response = Column(Text)
    image = Column(Text)   # (base64 image)
    logs = Column(Text)

Base.metadata.create_all(engine)