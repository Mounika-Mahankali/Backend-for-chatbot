from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from pydantic import BaseModel, field_validator
import hashlib, shutil, os, traceback, uuid, re
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from jose import jwt, JWTError
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi import BackgroundTasks


from rag import (
    load_rag,
    save_pdfs_to_db,
    save_image_description_to_db,
    vectorless_docs
)
from multimodal import get_response
from db import SessionLocal, User, Chat, ChatSession

from multimodal import speech_to_text
from multimodal import text_to_speech

from reportlab.pdfgen import canvas
from fastapi.responses import FileResponse

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
    allow_origins=["*"],
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


def get_session_file_paths(session: ChatSession):
    if not session.pdf_path:
        return []

    try:
        data = json.loads(session.pdf_path)
        if isinstance(data, list):
            return [path for path in data if isinstance(path, str)]
    except json.JSONDecodeError:
        pass

    return [session.pdf_path]


def set_session_file_paths(session: ChatSession, file_paths):
    session.pdf_path = json.dumps(file_paths)


def ensure_session_documents_loaded(session: ChatSession):
    if session.id in vectorless_docs:
        return

    stored_paths = [
        path for path in get_session_file_paths(session)
        if os.path.exists(path)
    ]

    if stored_paths:
        save_pdfs_to_db(stored_paths, chat_session_id=session.id)

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


# CHAT
@app.post("/chat")
def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user)
):
    db = SessionLocal()

    try:
        session = db.query(ChatSession).filter_by(
            id=request.session_id,
            user_id=current_user["user_id"]
        ).first()

        if not session:
            raise HTTPException(403, "Unauthorized session")

        ensure_session_documents_loaded(session)

        # SUMMARY COMMAND
        if "summar" in request.message.lower():

            msgs = db.query(Chat).filter_by(
                session_id=request.session_id
            ).all()

            text = "".join(
                [f"User:{m.message}\nBot:{m.response}\n" for m in msgs]
            )

            summary = get_response(f"Summarize:\n{text}")

            db.add(
                Chat(
                    session_id=request.session_id,
                    message=request.message,
                    response=summary
                )
            )

            session.summary = summary

            db.commit()

            return {
                "status": "success",
                "response": summary
            }

        # FETCH PREVIOUS CONVERSATIONS
        previous_chats = (
            db.query(Chat)
            .filter_by(session_id=request.session_id)
            .order_by(Chat.id.desc())
            .limit(3)
            .all()
        )

        # BUILD CONVERSATION CONTEXT
        conversation_context = ""

        for chat_item in reversed(previous_chats):

            conversation_context += f"""
User: {chat_item.message}
Assistant: {chat_item.response}
"""

        # ENHANCED QUERY WITH CONTEXT
        enhanced_query = f"""
Previous Conversation:
{conversation_context}

Current Question:
{request.message}
"""

        # RAG
        qa = load_rag(chat_session_id=request.session_id)

        response = qa(enhanced_query)

        # SAVE CHAT
        db.add(
            Chat(
                session_id=request.session_id,
                message=request.message,
                response=response
            )
        )

        db.commit()

        return {
            "status": "success",
            "response": response
        }

    except Exception as e:

        db.rollback()

        return {
            "status": "error",
            "details": str(e)
        }

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

        if not file.filename:
            raise HTTPException(400, "Missing file name")

        allowed_extensions = (".pdf", ".txt", ".docx", ".csv", ".pptx")
        file_extension = os.path.splitext(file.filename.lower())[1]

        if file_extension not in allowed_extensions:
            raise HTTPException(400, f"Invalid file type. Allowed: {', '.join(allowed_extensions)}")

        path = f"uploads/{uuid.uuid4()}_{file.filename}"
        os.makedirs("uploads", exist_ok=True)

        with open(path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        save_pdfs_to_db([path], chat_session_id=session_id)
        existing_paths = get_session_file_paths(session)
        existing_paths.append(path)
        set_session_file_paths(session, existing_paths)
        session.has_embeddings = 1
        session.embeddings_updated_at = datetime.utcnow()
        db.commit()

        return {
            "status": "success",
            "filename": file.filename,
            "session_id": session_id
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Document upload failed: {str(e)}")

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
        response = save_image_description_to_db(
            image_bytes=img,
            filename=file.filename or "uploaded_image",
            chat_session_id=session_id
        )

        db.add(Chat(session_id=session_id, message="Image uploaded", response=response))
        db.commit()

        return {"status": "success", "response": response}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Image upload failed: {str(e)}")

    finally:
        db.close()



# VOICE CHAT
@app.post("/voice-chat")
async def voice_chat(
    session_id: int,
    audio: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):

    db = SessionLocal()

    try:

        session = db.query(ChatSession).filter_by(
            id=session_id,
            user_id=current_user["user_id"]
        ).first()

        if not session:
            raise HTTPException(403, "Unauthorized session")

        ensure_session_documents_loaded(session)

        os.makedirs("temp_audio", exist_ok=True)

        audio_path = f"temp_audio/{audio.filename}"

        
        with open(audio_path, "wb") as buffer:
            buffer.write(await audio.read())   #await reads uploaded audio bytes
        transcribed_text = speech_to_text(audio_path)

        qa = load_rag(chat_session_id=session_id)
        response = qa(transcribed_text)
        audio_response_path = text_to_speech(response)
        db.add(
            Chat(
                session_id=session_id,
                message=transcribed_text,
                response=response
            )
        )

        db.commit()

        return {
            "status": "success",
            "transcribed_text": transcribed_text,
            "response": response
        }

    except Exception as e:

        db.rollback()

        return {
            "status": "error",
            "details": str(e)
        }

    finally:
        db.close()

def generate_chat_pdf(chats):

    os.makedirs("chat_exports", exist_ok=True)

    filename = f"chat_exports/{uuid.uuid4()}.pdf"

    c = canvas.Canvas(filename) #Canvas is new pdf file instance 

    y = 800

    c.setFont("Helvetica", 12)

    c.drawString(200, y, "Chat Export")

    y -= 40

    text_object = c.beginText(40, 800)

    text_object.setFont("Helvetica", 12)

    for chat in chats:

        text_object.textLine(f"User: {chat.message}")
        text_object.textLine("")

        
        response_lines = chat.response.split("\n")

        for line in response_lines:

            
            while len(line) > 100:

                text_object.textLine(line[:100])
                line = line[100:]

            text_object.textLine(line)

        text_object.textLine("")
        text_object.textLine("-" * 80)
        text_object.textLine("")

    c.drawText(text_object)

        # new page
    if y < 100:
        c.showPage()
        y = 800
        c.setFont("Helvetica", 12)

    c.save()

    return filename



@app.get("/export-chat/{session_id}")
def export_chat(
    session_id: int,
    current_user: dict = Depends(get_current_user)
):
    db = SessionLocal()

    try:
        session = db.query(ChatSession).filter_by(
            id=session_id,
            user_id=current_user["user_id"]
        ).first()

        if not session:
            raise HTTPException(403, "Unauthorized session")
        
        chats = db.query(Chat).filter_by(
            session_id=session_id
        ).all()

        if not chats:
            raise HTTPException(404, "No chats found")

        
        pdf_path = generate_chat_pdf(chats)
        return FileResponse(
            path=pdf_path,
            filename="chat_export.pdf",
            media_type="application/pdf"
        )

    finally:
        db.close()