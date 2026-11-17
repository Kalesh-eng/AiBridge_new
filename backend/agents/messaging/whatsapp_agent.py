"""
AIBridge WhatsApp Messaging Agent
Handles sending/receiving messages via Meta WhatsApp Cloud API.

Prerequisites:
- Meta Business Account verified (unlock error 131031)
- System User token (non-expiring) from Meta Business Manager
- Add to .env:
    WHATSAPP_TOKEN=<permanent_system_user_token>
    WHATSAPP_PHONE_NUMBER_ID=1460228647163898
"""
import os
import httpx
from typing import Optional
from .base_agent import BaseMessagingAgent, IncomingMessage


WHATSAPP_API = "https://graph.facebook.com/v25.0"


class WhatsAppAgent(BaseMessagingAgent):

    def __init__(self):
        self.token = os.getenv("WHATSAPP_TOKEN")
        self.phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
        if not self.token or not self.phone_number_id:
            print("[WhatsApp] WHATSAPP_TOKEN or WHATSAPP_PHONE_NUMBER_ID not set — WhatsApp disabled")

    @property
    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

    async def send_message(self, user_id: str, text: str) -> bool:
        """Send plain text message to a WhatsApp number."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{WHATSAPP_API}/{self.phone_number_id}/messages",
                headers=self._headers,
                json={
                    "messaging_product": "whatsapp",
                    "to": user_id,
                    "type": "text",
                    "text": {"body": text}
                }
            )
        return resp.status_code == 200

    async def send_report(self, user_id: str, title: str, data: list[dict]) -> bool:
        """Send formatted report as text (WhatsApp has no table support)."""
        text = self.format_report_as_text(title, data)

        # WhatsApp limit ~4096 chars; split if needed
        if len(text) > 4000:
            chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
            for chunk in chunks:
                await self.send_message(user_id, chunk)
            return True

        return await self.send_message(user_id, text)

    async def send_error(self, user_id: str, error: str) -> bool:
        return await self.send_message(user_id, f"❌ Error: {error}")

    async def handle_incoming(self, payload: dict) -> Optional[IncomingMessage]:
        """Parse WhatsApp webhook payload."""
        try:
            entry = payload["entry"][0]
            changes = entry["changes"][0]["value"]

            if "messages" not in changes:
                return None  # status update, not a message

            message = changes["messages"][0]
            contact = changes["contacts"][0]

            user_id = message["from"]
            user_name = contact.get("profile", {}).get("name", user_id)

            text = None
            audio_url = None

            if message["type"] == "text":
                text = message["text"]["body"]

            elif message["type"] in ("audio", "voice"):
                media_id = message[message["type"]]["id"]
                audio_url = await self._get_media_url(media_id)

            return IncomingMessage(
                channel="whatsapp",
                user_id=user_id,
                user_name=user_name,
                text=text,
                audio_url=audio_url,
                raw=payload
            )

        except Exception as e:
            print(f"[WhatsApp] Error parsing incoming: {e}")
            return None

    async def _get_media_url(self, media_id: str) -> Optional[str]:
        """Get downloadable URL for WhatsApp media (voice/audio)."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{WHATSAPP_API}/{media_id}",
                headers=self._headers
            )
            if resp.status_code != 200:
                return None
            return resp.json().get("url")

    async def send_daily_brief(self, user_id: str, brief: dict) -> bool:
        """Send the Monitor Agent 8AM daily brief."""
        lines = [
            "🌅 *AIBridge Daily Brief*",
            f"📅 {brief.get('date', 'Today')}",
            ""
        ]
        if brief.get("pipeline_status"):
            lines.append(f"⚙️ Pipelines: {brief['pipeline_status']}")
        if brief.get("records_processed"):
            lines.append(f"📊 Records: {brief['records_processed']:,}")
        if brief.get("alerts"):
            lines.append("\n⚠️ Alerts:")
            for alert in brief["alerts"]:
                lines.append(f"  • {alert}")
        if brief.get("summary"):
            lines.append(f"\n{brief['summary']}")

        return await self.send_message(user_id, "\n".join(lines))
