import base64
import io
import os
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from fastapi.responses import JSONResponse
from PIL import Image

from assistant import app as personal_assistant_app, memory, conn, llm

ACCESS_KEY = os.getenv("ACCESS_KEY")
ACCESS_DENIED_MESSAGE = "Sorry Only Prince Mehra can use this website"

if not ACCESS_KEY:
    raise ValueError("ACCESS_KEY is missing from the .env file! Set it to lock the app down.")


def verify_access(x_access_key: Optional[str] = Header(None)):
    """Every real endpoint below depends on this — enforced server-side so the
    lock can't be bypassed by calling the API directly instead of the website."""
    if x_access_key != ACCESS_KEY:
        raise HTTPException(status_code=401, detail=ACCESS_DENIED_MESSAGE)

VISION_MAX_DIMENSION = 320


def _shrink_image_for_vision(image_base64: str) -> str:
    """
    Downscales an image before sending it to the vision model, since the
    free-tier input-tokens-per-minute limit is easily exceeded by full-size photos.
    Always re-encodes as JPEG for small, predictable payload size.
    """
    raw_bytes = base64.b64decode(image_base64)
    with Image.open(io.BytesIO(raw_bytes)) as img:
        img = img.convert("RGB")
        img.thumbnail((VISION_MAX_DIMENSION, VISION_MAX_DIMENSION))
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=70)
        return base64.b64encode(buffer.getvalue()).decode()

app_fastapi = FastAPI(
    title="AI Personal Assistant API",
    description="An API to interact with the personal assistant."
)

app_fastapi.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str
    thread_id: str
    image_base64: Optional[str] = None
    image_mime_type: Optional[str] = None

class TitleUpdateRequest(BaseModel):
    title: str

class TitleGenerateRequest(BaseModel):
    message: str
    reply: Optional[str] = None

MAX_IMAGE_BASE64_CHARS = 27_000_000  # ~20MB raw image, base64-encoded

@app_fastapi.post("/api/chat")
async def chat(request: ChatRequest, _: None = Depends(verify_access)):
    if not request.message and not request.image_base64:
        return JSONResponse(content={"error": "Message not provided"}, status_code=400)

    if request.image_base64:
        if len(request.image_base64) > MAX_IMAGE_BASE64_CHARS:
            return JSONResponse(content={"error": "Image is too large (max ~20MB)."}, status_code=400)

        try:
            resized_base64 = _shrink_image_for_vision(request.image_base64)
        except Exception as e:
            print(f"!!! Failed to process image: {e}")
            return JSONResponse(content={"error": "Could not process the image. Please try a different file."}, status_code=400)

        message_content = [
            {"type": "text", "text": request.message or "What is in this image?"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{resized_base64}"}},
        ]
    else:
        message_content = request.message

    config = {"configurable": {"thread_id": request.thread_id}}
    response = personal_assistant_app.invoke({"messages": [HumanMessage(content=message_content)]}, config)

    final_response_content = response["messages"][-1].content

    return {"reply": final_response_content}

@app_fastapi.get("/api/history/{thread_id}")
async def get_history(thread_id: str, _: None = Depends(verify_access)):
    config = {"configurable": {"thread_id": thread_id}}
    checkpoint_tuple = memory.get_tuple(config)
    
    messages = []
    checkpoint = None

    if checkpoint_tuple:
        checkpoint = checkpoint_tuple.checkpoint

    if checkpoint and checkpoint.get('channel_values', {}).get('messages'):
            raw_messages = checkpoint['channel_values']['messages']
            
            for msg in raw_messages:

                if isinstance(msg, HumanMessage):
                    if isinstance(msg.content, list):
                        text_part = next(
                            (p.get("text", "") for p in msg.content if isinstance(p, dict) and p.get("type") == "text"),
                            ""
                        )
                        has_image = any(isinstance(p, dict) and p.get("type") == "image_url" for p in msg.content)
                        display_text = text_part + (" \U0001F4F7 [Image attached]" if has_image else "")
                        messages.append({"sender": "user", "text": display_text.strip()})
                    else:
                        messages.append({"sender": "user", "text": msg.content})

                elif isinstance(msg, AIMessage) and msg.content:
                    messages.append({"sender": "assistant", "text": msg.content})
                
    return {"messages": messages}


@app_fastapi.get("/api/threads")
async def get_threads(_: None = Depends(verify_access)):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.thread_id, m.title
        FROM checkpoints c
        LEFT JOIN chat_metadata m ON c.thread_id = m.thread_id
        GROUP BY c.thread_id
        ORDER BY MAX(c.checkpoint_id) DESC
    """)
    threads = cursor.fetchall()
    thread_list = [{"id": thread[0], "title": thread[1]} for thread in threads]
    return {"threads": thread_list}



@app_fastapi.post("/api/generate-title")
async def generate_title(request: TitleGenerateRequest, _: None = Depends(verify_access)):
    """
    Uses the LLM to derive a short, topical chat title from the first exchange,
    instead of just truncating the user's raw message.
    """
    exchange = f'User: "{request.message}"'
    if request.reply:
        exchange += f'\nAssistant: "{request.reply[:300]}"'

    prompt = f"""Based on this conversation opener, write a short chat title (2-5 words) that captures the topic.
Rules: No quotes, no trailing punctuation, no prefixes like "Title:". Title Case. Just the title text itself.

{exchange}
"""
    try:
        response = llm.invoke(prompt)
        title = str(response.content).strip().strip('"').strip("'").splitlines()[0][:60]
        if not title:
            title = request.message[:25]
    except Exception as e:
        print(f"!!! An error occurred in generate_title: {e}")
        title = request.message[:25]

    return {"title": title}


@app_fastapi.put("/api/threads/{thread_id}/title")
async def update_thread_title(thread_id: str, request: TitleUpdateRequest, _: None = Depends(verify_access)):
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO chat_metadata (thread_id, title) VALUES (?, ?)",
        (thread_id, request.title)
    )
    conn.commit()
    return {"status": "success", "thread_id": thread_id, "new_title": request.title}


@app_fastapi.delete("/api/threads/{thread_id}")
async def delete_thread(thread_id: str, _: None = Depends(verify_access)):
    """
    Deletes a specific thread and its metadata from the database.
    """
    print(f"--- Deleting Thread ID: {thread_id} ---")
    try:
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM chat_metadata WHERE thread_id = ?", (thread_id,))
        
        cursor.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
        
        conn.commit()
        
        return {"status": "success", "deleted_thread_id": thread_id}
    except Exception as e:
        conn.rollback() 
        print(f"!!! Error deleting thread {thread_id}: {e}")
        return JSONResponse(content={"error": f"Failed to delete thread: {e}"}, status_code=500)

@app_fastapi.get("/")
def read_root():
    return {"status": "AI Personal Assistant API is running."}