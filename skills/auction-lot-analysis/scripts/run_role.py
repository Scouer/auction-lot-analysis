#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Запуск роли навыка на внешнем провайдере (v2.4.0). Оркестратор (Claude) вызывает через Bash и читает только
результат — сырьё в контекст не идёт (принцип «нулевого транзита»).

  run_role.py --role historian --brief brief.md --search "запрос 1" --search "запрос 2" --out research/historian_glm.md
  run_role.py --role collector --brief brief.md --out research/collector_deepseek.md
  run_role.py --role reader    --images a.png b.png [--candidates 外 竹 作] --out research/reader_glm.md
  run_role.py --role reader2   --images a.png --out research/reader_gemini.md      # второе семейство (Gemini)
  run_role.py --role translate --brief listing.md --out source/listing_ru.md
  run_role.py --role market_text --brief listings_jp.md --out research/market_text.md

Провайдер/модель по умолчанию — providers.DEFAULTS; переопределить: --provider glm --model glm-5.3.
Guard приватности: бриф с фрагментами risk-profile / потолков ставки наружу не уходит.
Промпты ролей — providers/prompts/<role>.md (плейсхолдеры {brief}, {gathered}, {candidates}).
Выход: markdown + <out>.usage.json (usage, время, модель, повтор).
"""
import argparse, json, os, sys, re
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "providers"))
import providers as P

PROMPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "providers", "prompts")
PRIVATE_MARKERS = ["risk-profile", "Профиль покупателя", "Потолок на статус", "Условие сожаления", "Годовой бюджет",
                   "open_obligations", "maxim.russkikh", "scouer@"]


def guard(text):
    hits = [m for m in PRIVATE_MARKERS if m.lower() in text.lower()]
    if hits:
        sys.exit(f"STOP: бриф содержит личные данные ({', '.join(hits)}) — наружу не уходит (канон §3). Убери и повтори.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", required=True, choices=list(P.DEFAULTS))
    ap.add_argument("--provider"); ap.add_argument("--model")
    ap.add_argument("--brief", help="файл с брифом роли (md/txt)")
    ap.add_argument("--images", nargs="*", default=[])
    ap.add_argument("--search", action="append", default=[], help="запрос Perplexity (можно несколько) — сбор перед ролью")
    ap.add_argument("--search-model", default="sonar-pro")
    ap.add_argument("--candidates", nargs="*", default=[], help="варианты для forced-choice читателя")
    ap.add_argument("--max-tokens", type=int); ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    provider, model = P.DEFAULTS[a.role]
    provider = a.provider or provider; model = a.model or model
    brief = open(a.brief, encoding="utf-8").read() if a.brief else ""
    guard(brief)
    gathered = ""
    searches = []
    for q in a.search:
        r = P.perplexity_search(q, model=a.search_model)
        searches.append({"query": q, **r})
        gathered += f"\n=== Сбор Perplexity ({r['model']}): {q} ===\n{r['text']}\nСсылки: {json.dumps(r['citations'][:20], ensure_ascii=False)}\n"
    tpl = open(os.path.join(PROMPTS, a.role + ".md"), encoding="utf-8").read()
    prompt = tpl.replace("{brief}", brief).replace("{gathered}", gathered or "(сбор не выполнялся)") \
                .replace("{candidates}", " / ".join(a.candidates) if a.candidates else "любой")
    thinking = False if a.role in ("reader", "reader2", "translate") else None   # чтение и перевод — без рассуждения
    r = P.chat(provider, model, prompt, images=a.images or None, max_tokens=a.max_tokens, temperature=a.temperature, thinking=thinking)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    head = f"# {a.role} — {provider}/{model} (run_role.py, {r['sec']} с{', повтор с удвоенным бюджетом' if r['retried'] else ''})\n\n"
    if searches:
        head += "Сбор Perplexity: " + "; ".join(f"{s['model']} — {len(s['citations'])} ссылок, cost {s['cost']}" for s in searches) + "\n\n"
    open(a.out, "w", encoding="utf-8").write(head + (r["text"] or "(пустой ответ — проверь бюджет/модель)"))
    json.dump({"role": a.role, "provider": provider, "model": model, "usage": r["usage"], "sec": r["sec"], "max_tokens": r["max_tokens"],
               "retried": r["retried"], "searches": [{"query": s["query"], "citations": len(s["citations"]), "cost": s["cost"]} for s in searches]},
              open(a.out + ".usage.json", "w"), ensure_ascii=False, indent=1)
    print(f"{a.role} → {provider}/{model}: {len(r['text'])} симв., {r['sec']} с, usage {r['usage']}{' (повтор)' if r['retried'] else ''} → {a.out}")


if __name__ == "__main__":
    main()
