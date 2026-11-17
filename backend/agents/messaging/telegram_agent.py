"""
AIBridge Telegram Messaging Agent
Handles sending/receiving messages via Telegram Bot API.

Setup:
1. Create bot via @BotFather on Telegram -> /newbot
2. Add TELEGRAM_BOT_TOKEN to .env
3. Set webhook: POST https://api.telegram.org/bot<TOKEN>/setWebhook?url=<your_domain>/telegram/webhook
"""
import os
import httpx
from typing import Optional
from .base_agent import BaseMessagingAgent, IncomingMessage


TELEGRAM_API = "https://api.telegram.org/bot"


class TelegramAgent(BaseMessagingAgent):

    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN not set in environment")
        self.base_url = f"{TELEGRAM_API}{self.token}"

    async def send_message(self, user_id: str, text: str) -> bool:
        """Send plain text message. Supports Markdown formatting."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": user_id,
                    "text": text,
                    "parse_mode": "Markdown"
                }
            )
        return resp.status_code == 200

    async def send_report(self, user_id: str, title: str, data: list[dict]) -> bool:
        """Send formatted report. Uses Markdown table if small, text list if large."""
        text = self.format_report_as_text(title, data)

        # Telegram has 4096 char limit per message
        if len(text) > 4000:
            # Split into chunks
            chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
            for chunk in chunks:
                await self.send_message(user_id, chunk)
            return True

        return await self.send_message(user_id, text)

    async def send_error(self, user_id: str, error: str) -> bool:
        return await self.send_message(user_id, f"❌ Error: {error}")

    async def handle_incoming(self, payload: dict) -> Optional[IncomingMessage]:
        """Parse Telegram webhook payload."""
        try:
            message = payload.get("message") or payload.get("edited_message")
            if not message:
                return None

            user = message.get("from", {})
            chat_id = str(message["chat"]["id"])
            user_name = user.get("first_name", "") + " " + user.get("last_name", "")

            # Text message
            text = message.get("text")

            # Voice message
            audio_url = None
            if "voice" in message:
                file_id = message["voice"]["file_id"]
                audio_url = await self._get_file_url(file_id)

            # Audio file
            elif "audio" in message:
                file_id = message["audio"]["file_id"]
                audio_url = await self._get_file_url(file_id)

            return IncomingMessage(
                channel="telegram",
                user_id=chat_id,
                user_name=user_name.strip(),
                text=text,
                audio_url=audio_url,
                raw=payload
            )

        except Exception as e:
            print(f"[Telegram] Error parsing incoming: {e}")
            return None

    async def _get_file_url(self, file_id: str) -> Optional[str]:
        """Get downloadable URL for a Telegram file (voice/audio)."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.base_url}/getFile?file_id={file_id}")
            if resp.status_code != 200:
                return None
            file_path = resp.json()["result"]["file_path"]
            return f"https://api.telegram.org/file/bot{self.token}/{file_path}"

    async def set_webhook(self, webhook_url: str) -> bool:
        """Register webhook URL with Telegram."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/setWebhook",
                json={"url": webhook_url}
            )
        result = resp.json()
        print(f"[Telegram] Webhook set: {result}")
        return result.get("ok", False)

    async def send_daily_brief(self, user_id: str, brief: dict) -> bool:
        """Send the Monitor Agent 8AM daily brief."""
        lines = [
            "🌅 *AIBridge Daily Brief*",
            f"📅 {brief.get('date', 'Today')}",
            ""
        ]

        if brief.get("pipeline_status"):
            lines.append(f"⚙️ *Pipelines:* {brief['pipeline_status']}")

        if brief.get("records_processed"):
            lines.append(f"📊 *Records Processed:* {brief['records_processed']:,}")

        if brief.get("alerts"):
            lines.append("\n⚠️ *Alerts:*")
            for alert in brief["alerts"]:
                lines.append(f"  • {alert}")

        if brief.get("summary"):
            lines.append(f"\n📝 {brief['summary']}")

        return await self.send_message(user_id, "\n".join(lines))
