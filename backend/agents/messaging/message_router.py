
def _build_summary(rows, columns, query):
    if len(rows) == 1 and len(rows[0]) == 1:
        val = list(rows[0].values())[0]
        col = (columns[0] if columns else "result").replace("_", " ").title()
        if isinstance(val, (int, float)):
            return f"📊 *{col}*: *{val:,}*"
        return f"📊 *{col}*: {val}"
    return f"📊 Found *{len(rows)}* result(s)"


def _build_summary(rows, columns, query):
    if len(rows) == 1 and len(rows[0]) == 1:
        val = list(rows[0].values())[0]
        col = (columns[0] if columns else "result").replace("_", " ").title()
        if isinstance(val, (int, float)):
            return f"📊 *{col}*: *{val:,}*"
        return f"📊 *{col}*: {val}"
    return f"📊 Found *{len(rows)}* result(s)"


"""
AIBridge Message Router
Receives messages from any channel, processes NL query in any language,
returns report back to the same channel.

Flow:
  Incoming message (any language, text or voice)
    → detect language
    → translate to English
    → check for commands (/setpipeline, /pipelines, /help)
    → NL→SQL via /nl/to-sql  → get SQL
    → run SQL via /sql/run   → get rows
    → format report
    → translate response back to user's language
    → send via same channel

Commands:
  /pipelines          — list all available pipelines
  /setpipeline <id>   — set active pipeline for this user
  /setpipeline <name> — set by name (fuzzy match)
  /current            — show current active pipeline
  /help               — show available commands
"""
import os
import httpx
from typing import Optional
from .base_agent import IncomingMessage
from .telegram_agent import TelegramAgent
from .whatsapp_agent import WhatsAppAgent


class MessageRouter:

    def __init__(self):
        self.agents = {}

        if os.getenv("TELEGRAM_BOT_TOKEN"):
            self.agents["telegram"] = TelegramAgent()

        if os.getenv("WHATSAPP_TOKEN"):
            self.agents["whatsapp"] = WhatsAppAgent()

        self.aibridge_api = os.getenv("AIBRIDGE_API_URL", "http://localhost:8888")

        self._service_token: Optional[str] = os.getenv("AIBRIDGE_SERVICE_TOKEN")
        self._service_email = os.getenv("AIBRIDGE_SERVICE_EMAIL", "")
        self._service_password = os.getenv("AIBRIDGE_SERVICE_PASSWORD", "")

        # Per-user pipeline selection: {user_id: pipeline_id}
        self._user_pipelines: dict = {}

        # Global fallback pipeline (from .env)
        self.default_pipeline_id = os.getenv("AIBRIDGE_DEFAULT_PIPELINE_ID", "")
        self.default_connector_id = os.getenv("AIBRIDGE_DEFAULT_CONNECTOR_ID", "")

    # ── Auth ──────────────────────────────────────────────────────────────────

    async def _get_token(self) -> str:
        if self._service_token:
            return self._service_token
        if not self._service_email or not self._service_password:
            raise RuntimeError(
                "No auth configured. Set AIBRIDGE_SERVICE_TOKEN "
                "or AIBRIDGE_SERVICE_EMAIL + AIBRIDGE_SERVICE_PASSWORD in .env"
            )
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.aibridge_api}/auth/login",
                json={"email": self._service_email, "password": self._service_password}
            )
            resp.raise_for_status()
            data = resp.json()
            self._service_token = data.get("access_token") or data.get("token")
            if not self._service_token:
                raise RuntimeError(f"Login response had no token: {data}")
            return self._service_token

    def _auth_headers(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    # ── Pipeline helpers ──────────────────────────────────────────────────────

    def _get_user_pipeline(self, user_id: str) -> str:
        """Get active pipeline for this user, falling back to global default."""
        return self._user_pipelines.get(user_id, self.default_pipeline_id)

    async def _fetch_pipelines(self) -> list:
        """Fetch all pipelines from AIBridge API."""
        try:
            token = await self._get_token()
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.aibridge_api}/pipeline/list",
                    headers=self._auth_headers(token)
                )
                data = resp.json()
                return data.get("pipelines", [])
        except Exception as e:
            print(f"[Router] _fetch_pipelines error: {e}")
            return []

    # ── Command handlers ──────────────────────────────────────────────────────

    async def _handle_command(self, agent, msg: IncomingMessage) -> bool:
        """
        Handle bot commands. Returns True if command was handled (skip NL query).
        """
        text = msg.text.strip()

        # /help
        if text.lower() in ("/help", "help"):
            await agent.send_message(msg.user_id,
                "🤖 *AIBridge Bot Commands*\n\n"
                "/pipelines — List available pipelines\n"
                "/setpipeline <name or id> — Set active pipeline\n"
                "/current — Show active pipeline\n"
                "/help — Show this message\n\n"
                "Or just ask a question like:\n"
                "_show me total claims by policy type_"
            )
            return True

        # /pipelines
        if text.lower() in ("/pipelines", "list pipelines", "show pipelines"):
            pipelines = await self._fetch_pipelines()
            if not pipelines:
                await agent.send_message(msg.user_id, "❌ No pipelines found.")
                return True
            current = self._get_user_pipeline(msg.user_id)
            lines = ["📊 *Available Pipelines:*\n"]
            for p in pipelines:
                marker = "✅ " if p["id"] == current else "   "
                lines.append(f"{marker}`{p['name']}` — `/setpipeline {p['name']}`")
            lines.append("\n_✅ = currently active_")
            await agent.send_message(msg.user_id, "\n".join(lines))
            return True

        # /current
        if text.lower() in ("/current", "current pipeline", "which pipeline"):
            pid = self._get_user_pipeline(msg.user_id)
            if not pid:
                await agent.send_message(msg.user_id,
                    "No pipeline selected. Use /pipelines to see available ones, "
                    "then /setpipeline <name> to select one."
                )
            else:
                pipelines = await self._fetch_pipelines()
                name = next((p["name"] for p in pipelines if p["id"] == pid), pid)
                await agent.send_message(msg.user_id, f"✅ Active pipeline: *{name}*")
            return True

        # /setpipeline <name or id>
        if text.lower().startswith("/setpipeline ") or text.lower().startswith("use "):
            # Extract the pipeline name/id from the command
            if text.lower().startswith("/setpipeline "):
                query = text[13:].strip()
            else:
                # "use insurance pipeline show me claims" → extract pipeline name
                # Remove "use" prefix and common words
                query = text[4:].strip()
                for word in ["pipeline", "schema", "data"]:
                    query = query.replace(word, "").strip()

            pipelines = await self._fetch_pipelines()
            if not pipelines:
                await agent.send_message(msg.user_id, "❌ Could not fetch pipelines.")
                return True

            # Match by ID (exact) or name (fuzzy)
            matched = None
            query_lower = query.lower()
            for p in pipelines:
                if p["id"] == query or p["name"].lower() == query_lower:
                    matched = p
                    break
            if not matched:
                # Partial match
                for p in pipelines:
                    if query_lower in p["name"].lower() or p["name"].lower() in query_lower:
                        matched = p
                        break

            if matched:
                self._user_pipelines[msg.user_id] = matched["id"]
                await agent.send_message(msg.user_id,
                    f"✅ Pipeline set to *{matched['name']}*\n"
                    f"Now ask your question!"
                )
            else:
                names = "\n".join([f"• `{p['name']}`" for p in pipelines])
                await agent.send_message(msg.user_id,
                    f"❌ Pipeline '{query}' not found.\n\nAvailable:\n{names}"
                )
            return True

        return False  # not a command

    # ── Main entry point ──────────────────────────────────────────────────────

    async def handle(self, channel: str, payload: dict):
        agent = self.agents.get(channel)
        if not agent:
            print(f"[Router] No agent for channel: {channel}")
            return

        msg: IncomingMessage = await agent.handle_incoming(payload)
        if not msg:
            return

        # Transcribe audio if voice message
        if msg.audio_url and not msg.text:
            msg.text = await agent.transcribe_audio(msg.audio_url)
            if not msg.text:
                await agent.send_error(msg.user_id, "Could not understand audio. Please try again.")
                return

        if not msg.text:
            return

        print(f"[Router] [{channel}] {msg.user_name}: {msg.text}")

        # Check for commands first
        if await self._handle_command(agent, msg):
            return

        # Check if no pipeline selected
        pipeline_id = self._get_user_pipeline(msg.user_id)
        if not pipeline_id and not self.default_connector_id:
            pipelines = await self._fetch_pipelines()
            if pipelines:
                names = "\n".join([f"• `/setpipeline {p['name']}`" for p in pipelines])
                await agent.send_message(msg.user_id,
                    f"Please select a pipeline first:\n\n{names}"
                )
            else:
                await agent.send_error(msg.user_id, "No pipelines available. Please set up a pipeline in AIBridge first.")
            return

        # Detect language and translate to English if needed
        english_query, detected_lang = await self._translate_to_english(msg.text)

        # Process query via AIBridge NL→SQL pipeline
        result = await self._query_aibridge(english_query, msg.user_id, pipeline_id)

        if result.get("error"):
            error_msg = result["error"]
            if detected_lang != "en":
                error_msg = await self._translate_from_english(error_msg, detected_lang)
            await agent.send_error(msg.user_id, error_msg)
            return

        title = result.get("query_description", english_query)
        data = result.get("data", [])
        summary = result.get("summary", "")

        if detected_lang != "en":
            title = await self._translate_from_english(title, detected_lang)
            if summary:
                summary = await self._translate_from_english(summary, detected_lang)

        if summary:
            await agent.send_message(msg.user_id, summary)

        if data:
            await agent.send_report(msg.user_id, title, data)
        elif not summary:
            no_data_msg = "No data found for your query."
            if detected_lang != "en":
                no_data_msg = await self._translate_from_english(no_data_msg, detected_lang)
            await agent.send_message(msg.user_id, no_data_msg)

    # ── AIBridge query (NL → SQL → rows) ─────────────────────────────────────

    async def _query_aibridge(self, query: str, user_id: str, pipeline_id: str = "") -> dict:
        try:
            token = await self._get_token()
            headers = self._auth_headers(token)

            async with httpx.AsyncClient(timeout=30) as client:

                # Step 1: NL → SQL
                nl_payload = {
                    "question":     query,
                    "connector_id": self.default_connector_id,
                    ##"pipeline_id":  pipeline_id or self.default_pipeline_id,
                }
                nl_resp = await client.post(
                    f"{self.aibridge_api}/nl/to-sql",
                    headers=headers,
                    json=nl_payload
                )

                if nl_resp.status_code == 401:
                    self._service_token = None
                    token = await self._get_token()
                    headers = self._auth_headers(token)
                    nl_resp = await client.post(
                        f"{self.aibridge_api}/nl/to-sql",
                        headers=headers,
                        json=nl_payload
                    )

                nl_data = nl_resp.json()
                if not nl_data.get("success") or not nl_data.get("sql"):
                    return {"error": nl_data.get("error", "Could not generate SQL for your query.")}

                sql = nl_data["sql"]
                # Strip any prose prefix — extract just the SQL statement
                import re
                sql_match = re.search(r'(SELECT|INSERT|UPDATE|DELETE|WITH|CREATE)\b.*', sql, re.IGNORECASE | re.DOTALL)
                if sql_match:
                    sql = sql_match.group(0).strip()
                # Strip markdown code fences if present
                sql = re.sub(r'^```sql\s*', '', sql, flags=re.IGNORECASE).strip()
                sql = re.sub(r'^```\s*', '', sql).strip()
                sql = re.sub(r'\s*```$', '', sql).strip()
                print(f"[Router] Generated SQL: {sql[:120]}...")

                # Step 2: Run SQL
                run_resp = await client.post(
                    f"{self.aibridge_api}/sql/run",
                    headers=headers,
                    json={
                        "sql":          sql,
                        "connector_id": self.default_connector_id,
                    }
                )

                print(f"[Router] /sql/run status={run_resp.status_code} body={run_resp.text[:300]}")

                if run_resp.status_code == 404:
                    return {"error": f"SQL execution endpoint not found. Generated SQL was: {sql}"}

                run_data = run_resp.json()

                if not run_data.get("success") and "detail" in run_data:
                    return {"error": run_data["detail"]}

                if not run_data.get("success"):
                    real_error = run_data.get("error") or run_data.get("detail") or run_data.get("message") or str(run_data)
                    return {"error": f"SQL failed: {real_error}\nSQL was: {sql}"}

                rows    = run_data.get("rows", [])
                columns = run_data.get("columns", [])

                if rows and columns and not isinstance(rows[0], dict):
                    rows = [dict(zip(columns, row)) for row in rows]

                return {
                    "data":              rows,
                    "query_description": query,
                    "summary":           _build_summary(rows, columns, query),
                    "sql":               sql,
                }

        except RuntimeError as e:
            return {"error": str(e)}
        except Exception as e:
            print(f"[Router] _query_aibridge error: {e}")
            return {"error": str(e)}

    # ── Translation helpers ───────────────────────────────────────────────────

    async def _translate_to_english(self, text: str) -> tuple[str, str]:
        if text.isascii():
            return text, "en"
        try:
            import openai, json
            client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a translator. Detect the language of the user's message "
                            "and translate it to English. "
                            "Reply in JSON format: "
                            '{"detected_lang": "te", "english": "translated text"} '
                            "Use ISO 639-1 language codes (en, hi, te, ta, kn, ml, etc.)."
                        )
                    },
                    {"role": "user", "content": text}
                ],
                response_format={"type": "json_object"}
            )
            result = json.loads(response.choices[0].message.content)
            return result.get("english", text), result.get("detected_lang", "en")
        except Exception as e:
            print(f"[Router] Translation error: {e}")
            return text, "en"

    async def _translate_from_english(self, text: str, target_lang: str) -> str:
        if target_lang == "en":
            return text
        try:
            import openai
            client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"Translate the following text to language code '{target_lang}'. "
                            "Keep numbers, dates, and proper nouns as-is. "
                            "Reply with only the translated text, nothing else."
                        )
                    },
                    {"role": "user", "content": text}
                ]
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[Router] Reverse-translation error: {e}")
            return text
