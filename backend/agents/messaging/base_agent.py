"""
AIBridge Base Messaging Agent
Abstract interface for all messaging channels (Telegram, WhatsApp, Alexa, etc.)
"""
from abc import ABC, abstractmethod
from typing import Optional
import httpx
import os


class IncomingMessage:
    """Normalized incoming message from any channel."""
    def __init__(
        self,
        channel: str,           # "telegram", "whatsapp", "alexa"
        user_id: str,           # channel-specific user identifier
        user_name: str,
        text: Optional[str],
        audio_url: Optional[str] = None,
        raw: dict = None
    ):
        self.channel = channel
        self.user_id = user_id
        self.user_name = user_name
        self.text = text
        self.audio_url = audio_url
        self.raw = raw or {}


class BaseMessagingAgent(ABC):
    """
    Abstract base class for all AIBridge messaging channels.
    Each channel (Telegram, WhatsApp, Alexa) implements this interface.
    """

    @abstractmethod
    async def send_message(self, user_id: str, text: str) -> bool:
        """Send a plain text message to a user."""
        pass

    @abstractmethod
    async def send_report(self, user_id: str, title: str, data: list[dict]) -> bool:
        """Send a formatted report/table to a user."""
        pass

    @abstractmethod
    async def send_error(self, user_id: str, error: str) -> bool:
        """Send an error message to a user."""
        pass

    @abstractmethod
    async def handle_incoming(self, payload: dict) -> IncomingMessage:
        """Parse raw webhook payload into normalized IncomingMessage."""
        pass

    async def transcribe_audio(self, audio_url: str) -> Optional[str]:
        """
        Download audio and transcribe using OpenAI Whisper.
        Shared across all channels — override if channel needs special handling.
        """
        import openai
        import tempfile

        try:
            # Download audio file
            async with httpx.AsyncClient() as client:
                response = await client.get(audio_url)
                response.raise_for_status()

            # Save to temp file and transcribe
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
                f.write(response.content)
                temp_path = f.name

            client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            with open(temp_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file
                )
            return transcript.text

        except Exception as e:
            print(f"[Transcription Error] {e}")
            return None

    def format_report_as_text(self, title: str, data: list[dict]) -> str:
        """Format report data as plain text (fallback for all channels)."""
        if not data:
            return f"*{title}*\n\nNo data found."

        lines = [f"*{title}*\n"]
        for i, row in enumerate(data[:20], 1):  # limit to 20 rows
            row_lines = [f"{k}: {v}" for k, v in row.items()]
            lines.append(f"{i}. " + " | ".join(row_lines))

        if len(data) > 20:
            lines.append(f"\n_... and {len(data) - 20} more rows_")

        return "\n".join(lines)
