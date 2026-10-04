"""
whatsapp_agent.py
==================
AIBridge WhatsApp Integration
- Receives messages via Meta webhook
- Handles text and voice notes
- Whisper transcribes voice
- DeepSeek translates
- AIBridge generates SQL
- Sends reply with answer
"""

import os
import json
import requests
import tempfile
from ai_provider import ask_ai_text

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "aibridge_verify_2024")


def verify_webhook(mode: str, token: str, challenge: str) -> str:
    """Verify Meta webhook."""
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("[WhatsApp] Webhook verified!")
        return challenge
    return None


def send_message(to: str, message: str) -> dict:
    """Send text message via WhatsApp Cloud API."""
    url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message[:4000]}
    }
    try:
        r = requests.post(url, headers=headers, json=payload)
        print(f"[WhatsApp] Message sent to {to}: {r.status_code}")
        return r.json()
    except Exception as e:
        print(f"[WhatsApp] Send error: {e}")
        return {}


def download_media(media_id: str) -> bytes:
    """Download voice note or media from WhatsApp."""
    # Get media URL
    url = f"https://graph.facebook.com/v18.0/{media_id}"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    r = requests.get(url, headers=headers)
    media_url = r.json().get("url")

    # Download the actual media
    r2 = requests.get(media_url, headers=headers)
    return r2.content


def transcribe_audio(audio_bytes: bytes, lang: str = "") -> str:
    """Transcribe audio using local Whisper model."""
    import whisper
    import os

    # Add ffmpeg to path
    ffmpeg_path = r"E:\ffmpeg\ffmpeg-master-latest-win64-gpl\bin"
    if ffmpeg_path not in os.environ.get("PATH", ""):
        os.environ["PATH"] = os.environ.get("PATH", "") + f";{ffmpeg_path}"

    # Save audio to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        model = whisper.load_model("large")
        options = {"task": "transcribe", "fp16": False}
        if lang and lang != "en":
            options["language"] = lang
        result = model.transcribe(tmp_path, **options)
        text = result["text"].strip()
        detected = result.get("language", "en")
        print(f"[WhatsApp Whisper] Detected: {detected} | Text: {text}")
        return text, detected
    finally:
        os.unlink(tmp_path)


def detect_language(text: str) -> dict:
    """Detect language using DeepSeek."""
    from translation_agent import detect_language as _detect
    return _detect(text)


def translate_to_english(text: str, source_lang: str) -> str:
    """Translate to English using DeepSeek."""
    from translation_agent import translate_to_english as _translate
    result = _translate(text, source_lang)
    return result.get("english", text)


def translate_from_english(text: str, target_lang: str) -> str:
    """Translate from English to target language."""
    from translation_agent import translate_from_english as _translate
    return _translate(text, target_lang)


def query_aibridge(question: str, connector_id: str = "", pipeline_id: str = "", token: str = "") -> dict:
    """Send question to AIBridge /chat endpoint."""
    try:
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        r = requests.post(
            "http://localhost:8888/chat",
            json={"message": question, "connector_id": connector_id, "history": []},
            headers=headers,
            timeout=60
        )
        return r.json()
    except Exception as e:
        print(f"[WhatsApp] AIBridge query error: {e}")
        return {"response": "Sorry, I could not process your query.", "sql_result": None}


def format_response(response: str, sql_result: dict, lang: str = "en") -> str:
    """Format the response for WhatsApp."""
    msg = response.replace("```sql", "").replace("```", "").strip()

    if sql_result and sql_result.get("rows"):
        rows = sql_result["rows"]
        cols = sql_result["columns"]
        msg += f"\n\n📊 *Results ({len(rows)} rows):*\n"
        for row in rows[:5]:  # Show max 5 rows
            row_text = " | ".join(f"{cols[i]}: {row[i]}" for i in range(len(cols)))
            msg += f"• {row_text}\n"
        if len(rows) > 5:
            msg += f"_...and {len(rows)-5} more rows_"

    return msg


def process_whatsapp_message(body: dict, db, user_token: str = "") -> str:
    """
    Main handler for incoming WhatsApp messages.
    Handles both text and voice messages.
    """
    try:
        entry = body.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return "no_message"

        msg = messages[0]
        from_number = msg.get("from")
        msg_type = msg.get("type")

        print(f"[WhatsApp] Message from {from_number}, type: {msg_type}")

        # Send typing indicator
        send_message(from_number, "⏳ Processing your query...")

        text = ""
        detected_lang = "en"

        if msg_type == "text":
            # Text message
            text = msg.get("text", {}).get("body", "")
            lang_info = detect_language(text)
            detected_lang = lang_info.get("lang_code", "en")

        elif msg_type == "audio":
            # Voice note
            media_id = msg.get("audio", {}).get("id")
            if media_id:
                audio_bytes = download_media(media_id)
                text, detected_lang = transcribe_audio(audio_bytes)

        if not text:
            send_message(from_number, "❌ Could not understand your message. Please try again.")
            return "error"

        print(f"[WhatsApp] Text: {text} | Lang: {detected_lang}")

        # Translate to English if needed
        english_query = text
        if detected_lang != "en":
            english_query = translate_to_english(text, detected_lang)
            print(f"[WhatsApp] Translated: {english_query}")

        # Query AIBridge
        result = query_aibridge(english_query, token=user_token)
        english_response = result.get("response", "")
        sql_result = result.get("sql_result")

        # Format response
        formatted = format_response(english_response, sql_result)

        # Translate back if needed
        final_response = formatted
        if detected_lang != "en":
            final_response = translate_from_english(formatted, detected_lang)

        # Send reply
        send_message(from_number, final_response)
        print(f"[WhatsApp] Reply sent to {from_number}")
        return "success"

    except Exception as e:
        print(f"[WhatsApp] Error: {e}")
        return "error"


if __name__ == "__main__":
    print("WhatsApp Agent loaded!")
    print(f"Phone ID: {WHATSAPP_PHONE_ID or 'NOT SET'}")
    print(f"Token: {'SET' if WHATSAPP_TOKEN else 'NOT SET'}")
