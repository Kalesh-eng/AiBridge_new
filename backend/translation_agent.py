"""
translation_agent.py
====================
AIBridge TranslationAgent — zero cost multi-language support.
Uses DeepSeek for language detection + translation (already paid).
Used by: Browser voice, WhatsApp, Alexa, Mobile app.
"""

import json
import re
from ai_provider import ask_ai_text

SUPPORTED_LANGUAGES = {
    # Indian languages
    'hi': 'Hindi',
    'ta': 'Tamil',
    'te': 'Telugu',
    'kn': 'Kannada',
    'ml': 'Malayalam',
    'mr': 'Marathi',
    'gu': 'Gujarati',
    'bn': 'Bengali',
    'pa': 'Punjabi',
    # Middle East
    'ar': 'Arabic',
    'fa': 'Persian',
    'ur': 'Urdu',
    'tr': 'Turkish',
    'he': 'Hebrew',
    # East Asia
    'zh': 'Chinese (Mandarin)',
    'ja': 'Japanese',
    'ko': 'Korean',
    # Europe
    'ru': 'Russian',
    'de': 'German',
    'fr': 'French',
    'es': 'Spanish',
    'pt': 'Portuguese',
    'it': 'Italian',
    'nl': 'Dutch',
    'pl': 'Polish',
    'uk': 'Ukrainian',
    # Africa
    'sw': 'Swahili',
    'ha': 'Hausa',
    'yo': 'Yoruba',
    'zu': 'Zulu',
    'xh': 'Xhosa',
    'am': 'Amharic',
    'af': 'Afrikaans',
    'ig': 'Igbo',
    'so': 'Somali',
    'sn': 'Shona',
    'ms': 'Malay',
    # English (no translation needed)
    'en': 'English',
}

# Web Speech API language codes for browser TTS/STT
WEB_SPEECH_LANG_CODES = {
    'hi': 'hi-IN', 'ta': 'ta-IN', 'te': 'te-IN', 'kn': 'kn-IN',
    'ml': 'ml-IN', 'mr': 'mr-IN', 'gu': 'gu-IN', 'bn': 'bn-IN',
    'pa': 'pa-IN', 'ar': 'ar-SA', 'zh': 'zh-CN', 'ja': 'ja-JP',
    'ko': 'ko-KR', 'ru': 'ru-RU', 'de': 'de-DE', 'fr': 'fr-FR',
    'es': 'es-ES', 'pt': 'pt-BR', 'it': 'it-IT', 'nl': 'nl-NL',
    'pl': 'pl-PL', 'uk': 'uk-UA', 'tr': 'tr-TR', 'sw': 'sw-KE',
    'af': 'af-ZA', 'en': 'en-IN',
}


def detect_language(text: str) -> dict:
    """
    Detect the language of the given text.
    Returns: {"lang_code": "hi", "lang_name": "Hindi", "confidence": "high"}
    """
    prompt = f"""Detect the language of this text. Return ONLY a JSON object, nothing else.
Format: {{"lang_code": "hi", "lang_name": "Hindi", "confidence": "high"}}
Use ISO 639-1 two-letter language codes.
If English, return lang_code: "en".

Text: {text}

JSON only:"""

    try:
        result = ask_ai_text(prompt, agent_name="TranslationAgent")
        if isinstance(result, dict):
            return result
        # Parse if string
        clean = re.sub(r'```json|```', '', str(result)).strip()
        return json.loads(clean)
    except Exception as e:
        print(f"[TranslationAgent] Language detection failed: {e}")
        return {"lang_code": "en", "lang_name": "English", "confidence": "low"}


def translate_to_english(text: str, source_lang: str = "auto") -> dict:
    """
    Translate text to English.
    Returns: {"english": "translated text", "original_lang": "hi", "original_text": "..."}
    """
    if source_lang == "en":
        return {"english": text, "original_lang": "en", "original_text": text}

    # Auto-detect if needed
    if source_lang == "auto":
        detection = detect_language(text)
        source_lang = detection.get("lang_code", "en")
        if source_lang == "en":
            return {"english": text, "original_lang": "en", "original_text": text}

    lang_name = SUPPORTED_LANGUAGES.get(source_lang, source_lang)

    prompt = f"""Translate this {lang_name} text to English.
Return ONLY the English translation, nothing else, no explanations.

{lang_name} text: {text}

English translation:"""

    try:
        english = ask_ai_text(prompt, agent_name="TranslationAgent")
        if isinstance(english, dict):
            english = str(english)
        return {
            "english": english.strip(),
            "original_lang": source_lang,
            "original_text": text
        }
    except Exception as e:
        print(f"[TranslationAgent] Translation to English failed: {e}")
        return {"english": text, "original_lang": source_lang, "original_text": text}


def translate_from_english(text: str, target_lang: str) -> str:
    """
    Translate English text to target language.
    Returns translated string.
    """
    if target_lang == "en" or not target_lang:
        return text

    lang_name = SUPPORTED_LANGUAGES.get(target_lang, target_lang)

    prompt = f"""Translate this English text to {lang_name}.
Return ONLY the {lang_name} translation, nothing else.

English: {text}

{lang_name} translation:"""

    try:
        result = ask_ai_text(prompt, agent_name="TranslationAgent")
        if isinstance(result, dict):
            result = str(result)
        return result.strip()
    except Exception as e:
        print(f"[TranslationAgent] Translation from English failed: {e}")
        return text


def process_multilang_query(text: str, connector_id: str = "", pipeline_id: str = "") -> dict:
    """
    Full pipeline: detect language → translate to English → ready for AIBridge.
    Returns everything needed to process the query and respond in original language.
    """
    # Detect language
    detection = detect_language(text)
    lang_code = detection.get("lang_code", "en")
    lang_name = detection.get("lang_name", "English")

    print(f"[TranslationAgent] Detected: {lang_name} ({lang_code})")

    # Translate to English if needed
    if lang_code != "en":
        translation = translate_to_english(text, lang_code)
        english_query = translation["english"]
        print(f"[TranslationAgent] Translated: '{text}' → '{english_query}'")
    else:
        english_query = text

    return {
        "original_text":   text,
        "english_query":   english_query,
        "detected_lang":   lang_code,
        "detected_lang_name": lang_name,
        "needs_translation": lang_code != "en",
        "web_speech_code": WEB_SPEECH_LANG_CODES.get(lang_code, "en-IN"),
    }


def get_supported_languages() -> list:
    """Return list of supported languages for UI dropdown."""
    return [
        {
            "code": code,
            "name": name,
            "web_speech_code": WEB_SPEECH_LANG_CODES.get(code, f"{code}-{code.upper()}"),
            "flag": get_flag(code),
        }
        for code, name in SUPPORTED_LANGUAGES.items()
    ]


def get_flag(lang_code: str) -> str:
    """Return flag emoji for language."""
    flags = {
        'hi': '🇮🇳', 'ta': '🇮🇳', 'te': '🇮🇳', 'kn': '🇮🇳', 'ml': '🇮🇳',
        'mr': '🇮🇳', 'gu': '🇮🇳', 'bn': '🇧🇩', 'pa': '🇮🇳', 'ar': '🇸🇦',
        'fa': '🇮🇷', 'ur': '🇵🇰', 'tr': '🇹🇷', 'he': '🇮🇱', 'zh': '🇨🇳',
        'ja': '🇯🇵', 'ko': '🇰🇷', 'ru': '🇷🇺', 'de': '🇩🇪', 'fr': '🇫🇷',
        'es': '🇪🇸', 'pt': '🇧🇷', 'it': '🇮🇹', 'nl': '🇳🇱', 'pl': '🇵🇱',
        'uk': '🇺🇦', 'sw': '🇰🇪', 'ha': '🇳🇬', 'yo': '🇳🇬', 'zu': '🇿🇦',
        'xh': '🇿🇦', 'am': '🇪🇹', 'af': '🇿🇦', 'ig': '🇳🇬', 'so': '🇸🇴',
        'en': '🇬🇧',
    }
    return flags.get(lang_code, '🌐')


if __name__ == "__main__":
    # Test
    print("Testing TranslationAgent...")
    
    tests = [
        "How many claims were filed this month?",
        "इस महीने कितने दावे दर्ज किए गए?",
        "इस महीने कितने दावे दर्ज हुए हैं?",
    ]
    
    for text in tests:
        result = process_multilang_query(text)
        print(f"\nInput: {text}")
        print(f"Language: {result['detected_lang_name']}")
        print(f"English: {result['english_query']}")

