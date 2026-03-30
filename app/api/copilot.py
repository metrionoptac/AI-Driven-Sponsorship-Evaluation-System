"""
Copilot WebSocket API.
Provides a real-time chat interface powered by Claude with DB tool-use.
"""

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.copilot.agent import CopilotAgent

logger = logging.getLogger(__name__)

router = APIRouter(tags=["copilot"])

# Injected at startup
_agent: CopilotAgent | None = None


def init_copilot(agent: CopilotAgent):
    global _agent
    _agent = agent


# ----------------------------------------------------------------
# REST fallback (for environments where WS is tricky)
# ----------------------------------------------------------------

class ChatRequest(BaseModel):
    messages: list[dict]
    context: dict | None = None


class ChatResponse(BaseModel):
    reply: str


@router.get("/api/copilot/suggestion")
async def copilot_suggestion(page: str = "", request_id: str = ""):
    """D7: Get a proactive suggestion for the current page context."""
    if _agent is None:
        return {"suggestion": None}
    context = {"page": page}
    if request_id:
        context["request_id"] = request_id
    suggestion = await _agent.get_proactive_suggestion(page, context)
    return {"suggestion": suggestion}


@router.post("/api/copilot/chat", response_model=ChatResponse)
async def copilot_chat(req: ChatRequest):
    """REST endpoint for copilot chat (fallback if WebSocket unavailable)."""
    if _agent is None:
        return ChatResponse(reply="Copilot is not available — no database connection.")
    reply = await _agent.chat(req.messages, req.context)
    return ChatResponse(reply=reply)


# ----------------------------------------------------------------
# WebSocket endpoint
# ----------------------------------------------------------------

@router.websocket("/ws/copilot")
async def copilot_ws(websocket: WebSocket):
    """
    D9: WebSocket chat endpoint with tool-use step streaming.
    Client sends JSON: {"messages": [...], "context": {...}}
    Server sends:
      {"type": "tool_start", "tool_name": "..."} — when a tool is called
      {"type": "tool_result", "tool_name": "..."} — when a tool returns
      {"reply": "..."} — final text response
    """
    await websocket.accept()
    logger.info("Copilot WebSocket connected")

    if _agent is None:
        await websocket.send_json({"reply": "Copilot is not available — no database connection."})
        await websocket.close()
        return

    try:
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
                messages = payload.get("messages", [])
                context = payload.get("context")
            except (json.JSONDecodeError, AttributeError):
                await websocket.send_json({"reply": "Invalid message format."})
                continue

            # D9: Use streaming chat with tool-step callbacks
            async def on_tool_start(tool_name: str):
                try:
                    await websocket.send_json({"type": "tool_start", "tool_name": tool_name})
                except Exception:
                    pass

            async def on_tool_result(tool_name: str):
                try:
                    await websocket.send_json({"type": "tool_result", "tool_name": tool_name})
                except Exception:
                    pass

            reply = await _agent.chat(
                messages, context,
                on_tool_start=on_tool_start,
                on_tool_result=on_tool_result,
            )
            await websocket.send_json({"reply": reply})

    except WebSocketDisconnect:
        logger.info("Copilot WebSocket disconnected")
    except Exception as e:
        logger.exception("Copilot WS error: %s", e)
        try:
            await websocket.send_json({"reply": f"Error: {str(e)}"})
        except Exception:
            pass
