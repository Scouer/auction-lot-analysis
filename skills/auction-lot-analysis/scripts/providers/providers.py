#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Единый клиент внешних провайдеров для ролей навыка (v2.4.0).
Ключи — только из окружения (age-файл → ~/.zshenv, канон §3): ZAI_API_KEY (GLM), DEEPSEEK_API_KEY,
PERPLEXITY_API_KEY, GEMINI_API_KEY. Наружу уходят только публичные данные лота (см. run_role.py: guard).

Ловушки, найденные пилотом 2026-09-06 (лот WAKI-056), зашиты сюда:
- «думающие» модели (glm-5.x, deepseek-v4-pro) съедают max_tokens рассуждением и возвращают пустой text →
  минимальные бюджеты MIN_TOKENS + автоповтор с удвоенным бюджетом;
- у vision-моделей GLM thinking выключается параметром {"thinking": {"type": "disabled"}}; у текстового glm-5.3
  этот параметр даёт HTTP 400 — не передавать;
- GLM-4.6V не читает скоропись — как читатель не использовать (см. READER_MODELS).
"""
import os, json, base64, time, urllib.request, urllib.error

ENDPOINTS = {
    "glm": "https://api.z.ai/api/paas/v4/chat/completions",
    "deepseek": "https://api.deepseek.com/chat/completions",
    "perplexity": "https://api.perplexity.ai/chat/completions",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
}
KEYS = {"glm": "ZAI_API_KEY", "deepseek": "DEEPSEEK_API_KEY", "perplexity": "PERPLEXITY_API_KEY", "gemini": "GEMINI_API_KEY"}
MIN_TOKENS = {"glm-5.3": 16000, "glm-5.2": 16000, "glm-5.1": 16000, "glm-5": 16000, "glm-5.3-flash": 8000,
              "deepseek-v4-pro": 12000, "deepseek-v4-flash": 8000, "deepseek-v4-flash-vision-exp": 12000}
DEFAULTS = {  # роль → (provider, model)
    "historian": ("glm", "glm-5.3"),
    "collector": ("deepseek", "deepseek-v4-pro"),
    "reader": ("glm", "glm-5v-turbo"),
    "reader2": ("deepseek", "deepseek-v4-flash-vision-exp"),   # второе семейство; Gemini (2.5-flash) — третий голос при расхождении
    "translate": ("gemini", "gemini-2.5-flash"),   # thinking off: glm-5.3-flash сжёг 11.8k reasoning на 7 строк перевода (пилот)
    "market_text": ("deepseek", "deepseek-v4-flash"),
}
READER_MODELS_BANNED = {"glm-4.6v"}   # галлюцинирует на скорописи (пилот 2026-09-06)


def _key(provider):
    k = os.environ.get(KEYS[provider])
    if not k:
        raise SystemExit(f"{KEYS[provider]} не задан в окружении (age-файл / ~/.zshenv)")
    return k


def _post(url, body, headers, timeout=600, retries=2):
    data = json.dumps(body).encode()
    for a in range(retries + 1):
        try:
            r = urllib.request.Request(url, data=data, headers=headers)
            return json.load(urllib.request.urlopen(r, timeout=timeout))
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="ignore")[:300]
            if e.code in (429, 500, 502, 503) and a < retries:
                time.sleep(5 * (a + 1)); continue
            raise RuntimeError(f"HTTP {e.code}: {msg}")
        except Exception as ex:
            if a < retries:
                time.sleep(4 * (a + 1)); continue
            raise


def _img_part_openai(path):
    ext = os.path.splitext(path)[1].lstrip(".").lower() or "png"
    ext = "jpeg" if ext == "jpg" else ext
    b64 = base64.b64encode(open(path, "rb").read()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/{ext};base64,{b64}"}}


def chat(provider, model, prompt, images=None, max_tokens=None, temperature=0.2, thinking=None, system=None):
    """Один вызов. Возвращает dict: text, usage, sec, provider, model, retried."""
    if model in READER_MODELS_BANNED and images:
        raise SystemExit(f"{model} запрещён как читатель изображений (галлюцинирует на скорописи)")
    mt = max(max_tokens or 0, MIN_TOKENS.get(model, 4000))
    t0 = time.time(); retried = False
    for attempt in range(2):
        if provider == "gemini":
            parts = [{"text": prompt}]
            for p in (images or []):
                ext = os.path.splitext(p)[1].lstrip(".").lower() or "png"; ext = "jpeg" if ext == "jpg" else ext
                parts.append({"inline_data": {"mime_type": f"image/{ext}", "data": base64.b64encode(open(p, "rb").read()).decode()}})
            body = {"contents": [{"role": "user", "parts": parts}],
                    "generationConfig": {"temperature": temperature, "maxOutputTokens": mt}}
            if thinking is False and "flash" in model:    # выключить рассуждение можно только у flash-моделей (pro — HTTP 400)
                body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
            if system: body["systemInstruction"] = {"parts": [{"text": system}]}
            j = _post(ENDPOINTS["gemini"].format(model=model) + "?key=" + _key("gemini"), body, {"Content-Type": "application/json"})
            cands = j.get("candidates") or [{}]
            text = "".join(p.get("text", "") for p in (cands[0].get("content") or {}).get("parts", []))
            usage = j.get("usageMetadata")
        else:
            content = ([_img_part_openai(p) for p in (images or [])] + [{"type": "text", "text": prompt}]) if images else prompt
            msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": content}]
            body = {"model": model, "messages": msgs, "temperature": temperature, "max_tokens": mt}
            if thinking is not None and provider == "glm" and (images or model.endswith("v") or "v-" in model):
                body["thinking"] = {"type": "enabled" if thinking else "disabled"}
            j = _post(ENDPOINTS[provider], body, {"Authorization": "Bearer " + _key(provider), "Content-Type": "application/json"})
            m = j["choices"][0]["message"]; text = m.get("content") or ""; usage = j.get("usage")
        if text.strip():
            break
        # пустой текст = рассуждение съело бюджет → один повтор с удвоенным бюджетом
        mt = min(mt * 2, 32000); retried = True
    return {"text": text, "usage": usage, "sec": round(time.time() - t0, 1), "provider": provider, "model": model,
            "max_tokens": mt, "retried": retried}


def perplexity_search(query, model="sonar-pro", max_tokens=900):
    """Сбор источников. Результат = tier-3 черновик (канон §9): ссылки читать самому, два источника с датой."""
    j = _post(ENDPOINTS["perplexity"], {"model": model, "messages": [{"role": "user", "content": query}], "max_tokens": max_tokens},
              {"Authorization": "Bearer " + _key("perplexity"), "Content-Type": "application/json"}, timeout=180)
    return {"text": j["choices"][0]["message"]["content"], "citations": j.get("citations", []),
            "cost": (j.get("usage") or {}).get("cost"), "model": model}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="ping провайдера: providers.py glm glm-5.3-flash 'скажи ok'")
    ap.add_argument("provider"); ap.add_argument("model"); ap.add_argument("prompt")
    a = ap.parse_args(); r = chat(a.provider, a.model, a.prompt, max_tokens=64)
    print(json.dumps({k: v for k, v in r.items() if k != "usage"}, ensure_ascii=False)); print(r["text"][:300])
