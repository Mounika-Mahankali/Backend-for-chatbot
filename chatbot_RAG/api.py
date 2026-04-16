from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from pydantic import BaseModel, field_validator
import hashlib, shutil, os, traceback, uuid, re
from datetime import datetime, timedelta
from dotenv import load_dotenv
from jose import jwt, JWTError
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi import BackgroundTasks

from rag import load_rag, save_pdfs_to_db, generate_image_response
from multimodal import get_response
from db import SessionLocal, User, Chat, ChatSession

#  ENV 
load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 2

if not SECRET_KEY:
    raise ValueError("SECRET_KEY not set in .env")

# APP 
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer()

# MODELS 
class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    password: str

    @field_validator("password")
    def validate_password(cls, value):
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", value):
            raise ValueError("Password must contain special character")
        return value

class ChatRequest(BaseModel):
    message: str
    session_id: int

class RenameRequest(BaseModel):
    title: str

# AUTH 
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        return {"user_id": payload.get("user_id"), "username": payload.get("username")}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

#  BASIC 
@app.get("/")
def home():
    return {"status": "success", "message": "API running"}

#  REGISTER 
@app.post("/register")
def register(request: RegisterRequest):
    db = SessionLocal()
    try:
        user = User(
            username=request.username,
            password=hashlib.sha256(request.password.encode()).hexdigest()
        )
        db.add(user)
        db.commit()
        return {"status": "success", "message": "User registered"}
    except Exception as e:
        db.rollback()
        return {"status": "error", "details": str(e)}
    finally:
        db.close()

#  LOGIN 
@app.post("/login")
def login(request: LoginRequest):
    db = SessionLocal()
    try:
        hashed = hashlib.sha256(request.password.encode()).hexdigest()
        user = db.query(User).filter_by(username=request.username).first()

        if not user:
            raise HTTPException(404, "User not found")
        if user.password != hashed:
            raise HTTPException(401, "Incorrect password")

        token = create_access_token({"user_id": user.id, "username": user.username})

        return {
            "status": "success",
            "user_id": user.id,
            "username": user.username,
            "access_token": token,
            "token_type": "bearer"
        }
    finally:
        db.close()

#  PROFILE 
@app.get("/profile")
def profile(current_user: dict = Depends(get_current_user)):
    return {"status": "success", "data": current_user}

#  CHAT SESSION 
@app.post("/new-chat")
def new_chat(current_user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        chat = ChatSession(user_id=current_user["user_id"], title="New Chat")
        db.add(chat)
        db.commit()
        db.refresh(chat)
        return {"status": "success", "chat_id": chat.id}
    finally:
        db.close()

@app.get("/chats")
def get_chats(current_user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        chats = db.query(ChatSession).filter_by(user_id=current_user["user_id"]).all()
        return {"status": "success", "data": chats}
    finally:
        db.close()

@app.delete("/chat/{chat_id}")
def delete_chat(chat_id: int, current_user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        session = db.query(ChatSession).filter_by(id=chat_id, user_id=current_user["user_id"]).first()
        if not session:
            raise HTTPException(403, "Unauthorized")

        db.query(Chat).filter_by(session_id=chat_id).delete()
        db.query(ChatSession).filter_by(id=chat_id).delete()
        db.commit()

        return {"status": "success", "message": "Chat deleted"}
    finally:
        db.close()

@app.put("/chat/{chat_id}")
def rename_chat(chat_id: int, request: RenameRequest, current_user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        session = db.query(ChatSession).filter_by(id=chat_id, user_id=current_user["user_id"]).first()
        if not session:
            raise HTTPException(403, "Unauthorized")

        session.title = request.title
        db.commit()

        return {"status": "success", "message": "Renamed"}
    finally:
        db.close()

#  CHAT 
@app.post("/chat")
def chat(request: ChatRequest, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        session = db.query(ChatSession).filter_by(id=request.session_id, user_id=current_user["user_id"]).first()
        if not session:
            raise HTTPException(403, "Unauthorized session")

        # SUMMARY COMMAND
        if "summar" in request.message.lower():
            msgs = db.query(Chat).filter_by(session_id=request.session_id).all()
            text = "".join([f"User:{m.message}\nBot:{m.response}\n" for m in msgs])

            summary = get_response(f"Summarize:\n{text}")

            db.add(Chat(session_id=request.session_id, message=request.message, response=summary))
            session.summary = summary
            db.commit()

            return {"status": "success", "response": summary}

        # RAG
        qa = load_rag(chat_session_id=request.session_id)
        response = qa(request.message)

        db.add(Chat(session_id=request.session_id, message=request.message, response=response))
        db.commit()

        return {"status": "success", "response": response}

    except Exception as e:
        db.rollback()
        return {"status": "error", "details": str(e)}
    finally:
        db.close()

#  HISTORY 
@app.get("/chat-history/{session_id}")
def history(session_id: int, current_user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        session = db.query(ChatSession).filter_by(id=session_id, user_id=current_user["user_id"]).first()
        if not session:
            raise HTTPException(403, "Unauthorized")

        chats = db.query(Chat).filter_by(session_id=session_id).all()
        return {"status": "success", "data": chats}
    finally:
        db.close()

# DOC UPLOAD 
@app.post("/upload-docs")
async def upload_docs(session_id: int, file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        session = db.query(ChatSession).filter_by(id=session_id, user_id=current_user["user_id"]).first()
        if not session:
            raise HTTPException(403, "Unauthorized")

        if not file.filename.endswith((".pdf", ".txt", ".docx")):
            raise HTTPException(400, "Invalid file")

        path = f"uploads/{uuid.uuid4()}_{file.filename}"
        os.makedirs("uploads", exist_ok=True)

        with open(path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        save_pdfs_to_db([path], chat_session_id=session_id)

        return {"status": "success", "message": "Uploaded"}

    finally:
        db.close()

# IMAGE 
@app.post("/upload-image")
async def upload_image(session_id: int, file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        session = db.query(ChatSession).filter_by(id=session_id, user_id=current_user["user_id"]).first()
        if not session:
            raise HTTPException(403, "Unauthorized")

        img = await file.read()
        response = generate_image_response("Describe image", img)

        db.add(Chat(session_id=session_id, message="Image uploaded", response=response))
        db.commit()

        return {"status": "success", "response": response}

    finally:
        db.close()