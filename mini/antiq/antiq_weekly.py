#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""antiq_weekly.py — недельная сверка с кабинетом Invaluable (локально, headless Chrome).

  login   один раз: откроется обычное окно Chrome с отдельным профилем — залогиниться
          на invaluable.com под «Qwintry Maksim» и закрыть окно. Сессия сохранится.
  check   снять страницы purchases, сравнить с базой лотов в Notion, отчитаться в TG.

Ничего не покупает и не нажимает — только читает страницы своего кабинета."""
import json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import antiq_lib as A

PROFILE = os.path.join(A.ANTIQ, "chrome-profile")
PAGES   = 4

def chrome(args, timeout=180):
    return subprocess.run([A.CHROME, "--user-data-dir=" + PROFILE] + args,
                          capture_output=True, text=True, timeout=timeout)

def login():
    os.makedirs(PROFILE, exist_ok=True)
    print("Откроется Chrome с отдельным профилем. Залогинься на Invaluable и закрой окно.")
    subprocess.run([A.CHROME, "--user-data-dir=" + PROFILE, "--no-first-run",
                    "https://www.invaluable.com/login"])
    print("Профиль сохранён:", PROFILE)

def dump(url):
    r = chrome(["--headless=new", "--disable-gpu", "--virtual-time-budget=25000",
                "--run-all-compositor-stages-before-draw", "--dump-dom", url])
    return r.stdout or ""

CARD = re.compile(r'/my-account/invoice/([0-9A-Fa-f]{8,12})')
LOTA = re.compile(r'href="(/auction-lot/[^"]+?-([0-9a-f]{8,12}))"')
IMG  = re.compile(r'(https://image\.invaluable\.com/housePhotos/[^"\s\\]+)')
TITL = re.compile(r'Lot\s+(\d+[a-zA-Z]?):\s*([^<\n]{3,120})')

def parse(htmldoc):
    """Возвращает {lotRef: {url, img, lot, title}} — по совпадению хвоста ссылки лота с lotRef."""
    found = {}
    for href, tail in LOTA.findall(htmldoc):
        found[tail.upper()] = {"url": "https://www.invaluable.com" + href, "img": "", "lot": "", "title": ""}
    refs = set(r.upper() for r in CARD.findall(htmldoc))
    imgs = IMG.findall(htmldoc)
    titles = TITL.findall(htmldoc)
    for i, ref in enumerate(sorted(refs)):
        d = found.setdefault(ref, {"url": "", "img": "", "lot": "", "title": ""})
        if i < len(imgs): d["img"] = imgs[i]
        if i < len(titles): d["lot"], d["title"] = titles[i][0], titles[i][1].strip()
    return {r: d for r, d in found.items() if r in refs or d["url"]}

def check():
    if not os.path.isdir(PROFILE):
        A.tg("🏺 Антиквариат: недельная сверка не выполнена — нет сессии Invaluable.\n"
             "Запусти один раз на Mini:\n/usr/bin/python3 ~/.claude-assistant/antiq/antiq_weekly.py login")
        A.log("нет профиля Chrome — нужен login"); return
    known = set()
    for l in A.nq(A.DB_LOTS):
        r = A.gtext(l, "lotRef Invaluable")
        if r: known.add(r.upper())
    seen, logged_out = {}, False
    for p in range(1, PAGES + 1):
        doc = dump("https://www.invaluable.com/my-account/purchases?page=%d" % p)
        if "sign in" in doc.lower()[:4000] or "log in" in doc.lower()[:4000]:
            logged_out = True; break
        seen.update(parse(doc))
        A.log("страница %d: карточек %d" % (p, len(seen)))
    if logged_out or not seen:
        A.tg("🏺 Антиквариат: сессия Invaluable протухла — недельная сверка не прошла.\n"
             "Обнови вход: /usr/bin/python3 ~/.claude-assistant/antiq/antiq_weekly.py login")
        A.log("сессия протухла"); return
    new = {r: d for r, d in seen.items() if r not in known}
    st = A.state(); st["last_weekly_iso"] = A.iso(A.now()); st["weekly_seen"] = len(seen)
    A.save_state(st)
    if not new:
        A.log("новых лотов нет (в кабинете %d, в Notion %d)" % (len(seen), len(known)))
        A.tg("🏺 Антиквариат, недельная сверка: новых покупок нет. В кабинете %d лотов, в базе %d."
             % (len(seen), len(known)))
        return
    lines = ["🏺 Антиквариат: в кабинете есть покупки, которых нет в базе — %d" % len(new), ""]
    for r, d in sorted(new.items()):
        lines.append("• Лот %s %s\n  %s" % (d["lot"] or "?", (d["title"] or "")[:70], d["url"] or r))
    lines.append("\nЗаведу карточки и досье по команде — напиши «заведи новые лоты».")
    open(os.path.join(A.ANTIQ, "new_lots.json"), "w").write(json.dumps(new, ensure_ascii=False, indent=1))
    A.tg("\n".join(lines)[:3900])
    A.log("новых лотов: %d (сохранены в new_lots.json)" % len(new))

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    (login if cmd == "login" else check)()
