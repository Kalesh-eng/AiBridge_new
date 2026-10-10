"""
AI_Commander — AIBridge's orchestration brain.
Scores every SLM response (0-100). If score < threshold, escalates to cloud LLM.
No Chinese LLMs. Compliant with US, EU, UK, India, Australia clients.
"""
import httpx
import json
import os

OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

SLM_ROUTES = {
    "sql":      "sqlcoder:latest",
    "strategy": "mistral:latest",
    "code":     "starcoder2:latest",
    "monitor":  "phi3.5:latest",
    "general":  "mistral:latest",
}

SCORE_THRESHOLD = 70


def ask_slm(task_type: str, prompt: str, system: str = "") -> dict:
    model = SLM_ROUTES.get(task_type, SLM_ROUTES["general"])
    # sqlcoder needs special prompt format
    if "sqlcoder" in model:
        formatted_prompt = f"""### Task
Generate a SQL query to answer the following question.
### Question
{prompt}
### SQL
"""
    else:
        formatted_prompt = prompt
    payload = {
        "model": model,
        "prompt": formatted_prompt,
        "system": system or "You are a helpful AI assistant.",
        "stream": False
    }
    try:
        resp = httpx.post(f"{OLLAMA_BASE}/api/generate", json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return {"response": data.get("response", ""), "model": model}
    except Exception as e:
        return {"response": "", "model": model, "error": str(e)}


def score_response(question: str, response: str) -> int:
    if not response or len(response.strip()) < 10:
        return 0
    scoring_prompt = f"""Score this response 0-100 for accuracy and helpfulness.
Respond with ONLY JSON: {{"score": 85, "reason": "brief reason"}}

Question: {question[:500]}
Response: {response[:1000]}

Score:"""
    try:
        result = httpx.post(
            f"{OLLAMA_BASE}/api/generate",
            json={"model": "nous-hermes2:latest", "prompt": scoring_prompt,
                  "stream": False, "options": {"temperature": 0.1}},
            timeout=60
        )
        text = result.json().get("response", "")
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(text[start:end])
            return max(0, min(100, int(data.get("score", 50))))
    except Exception:
        pass
    return 50


def route_with_commander(task_type: str, prompt: str, system: str = "",
                          cloud_fallback_fn=None) -> dict:
    slm_result = ask_slm(task_type, prompt, system)
    slm_response = slm_result.get("response", "")

    if slm_result.get("error"):
        if cloud_fallback_fn:
            return {"response": cloud_fallback_fn(prompt, system),
                    "source": "cloud", "score": 0}
        return {"response": "", "source": "error", "score": 0}

    score = score_response(prompt, slm_response)

    if score >= SCORE_THRESHOLD:
        return {"response": slm_response,
                "source": f"slm:{slm_result['model']}", "score": score}

    if cloud_fallback_fn:
        return {"response": cloud_fallback_fn(prompt, system),
                "source": "cloud", "score": score,
                "reason": f"SLM score {score} below threshold {SCORE_THRESHOLD}"}

    return {"response": slm_response,
            "source": f"slm:{slm_result['model']}", "score": score}


def health_check() -> dict:
    try:
        resp = httpx.get(f"{OLLAMA_BASE}/api/tags", timeout=10)
        models = [m["name"] for m in resp.json().get("models", [])]
        return {"status": "ok", "models": models, "ollama_url": OLLAMA_BASE}
    except Exception as e:
        return {"status": "error", "error": str(e), "ollama_url": OLLAMA_BASE}
