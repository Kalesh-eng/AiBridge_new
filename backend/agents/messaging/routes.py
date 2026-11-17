"""
AIBridge Messaging Webhook Routes
Add these to your existing FastAPI app (main.py or routers/)
"""
from fastapi import APIRouter, Request, Response
from .message_router import MessageRouter

router = APIRouter(prefix="/messaging", tags=["messaging"])
message_router = MessageRouter()


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    payload = await request.json()
    await message_router.handle("telegram", payload)
    return {"ok": True}


@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    payload = await request.json()
    await message_router.handle("whatsapp", payload)
    return {"ok": True}


@router.get("/whatsapp/webhook")
async def whatsapp_verify(request: Request):
    """WhatsApp webhook verification."""
    params = dict(request.query_params)
    if params.get("hub.verify_token") == "aibridge_webhook_token":
        return Response(content=params["hub.challenge"])
    return Response(status_code=403)


@router.post("/alexa/webhook")
async def alexa_webhook(request: Request):
    """Alexa skill handler — routes to AIBridge query."""
    payload = await request.json()
    await message_router.handle("alexa", payload)
    return {"version": "1.0", "response": {"outputSpeech": {"type": "PlainText", "text": "Done."}}}
