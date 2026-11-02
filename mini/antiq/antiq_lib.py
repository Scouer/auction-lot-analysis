#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""antiq_lib.py — общая библиотека контура «Антиквариат» (локально на Mini).
Notion REST + Gmail(scouer@) + Telegram + NotebookLM CLI + трекинг.
Секреты берутся из notion.env / tg-bot.env и НИКОГДА не пишутся в лог."""
import base64, json, os, re, subprocess, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

DIR   = os.path.expanduser("~/.claude-assistant")
ANTIQ = os.path.join(DIR, "antiq")
LOG   = os.path.join(ANTIQ, "antiq.log")
STATE = os.path.join(ANTIQ, "state.json")
PDFS  = os.path.join(ANTIQ, "pdf")
IMGS  = os.path.join(ANTIQ, "img")
MSK   = timezone(timedelta(hours=3))

DB_INVOICES = "226d2214956242b4ac739bad66e8e496"
DB_LOTS     = "093548f1567a406c889c41275501e89e"
DB_CORR     = "fcec0f33ed114f918e251e9904c64104"
NOTEBOOK    = "78b9a001-0747-42e8-b358-ee2b52a2ccdc"
NLM         = os.path.expanduser("~/.local/bin/nlm")
CHROME      = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
TG_CHAT     = "57790549"

for d in (ANTIQ, PDFS, IMGS):
    os.makedirs(d, exist_ok=True)

# ---------- служебное ----------
def now(): return int(time.time())
def iso(ts): return datetime.fromtimestamp(ts, MSK).isoformat(timespec="seconds")
def today(): return datetime.now(MSK).strftime("%Y-%m-%d")

def log(msg):
    line = "%s %s" % (iso(now()), msg)
    with open(LOG, "a") as f:
        f.write(line + "\n")
    print(line, flush=True)

def _envfile(path):
    out = {}
    try:
        for line in open(os.path.expanduser(path)):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except IOError:
        pass
    return out

_CFG = None
def cfg():
    global _CFG
    if _CFG is None:
        c = {}
        c.update(_envfile(os.path.join(DIR, "notion.env")))
        c.update(_envfile(os.path.join(DIR, "tg-bot.env")))
        _CFG = c
    return _CFG

def state():
    try: return json.load(open(STATE))
    except Exception: return {}
def save_state(d):
    json.dump(d, open(STATE, "w"), ensure_ascii=False, indent=1)

# ---------- Notion ----------
def _nreq(url, method="GET", payload=None):
    req = urllib.request.Request(url, method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": "Bearer " + cfg()["NOTION_TOKEN"],
                 "Notion-Version": "2022-06-28", "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            return json.load(urllib.request.urlopen(req, timeout=45))
        except Exception as e:
            if attempt == 2: raise
            time.sleep(2 + attempt * 3)

def nq(dbid, flt=None):
    """Все страницы базы (с пагинацией)."""
    out, cur = [], None
    while True:
        body = {"page_size": 100}
        if flt: body["filter"] = flt
        if cur: body["start_cursor"] = cur
        r = _nreq("https://api.notion.com/v1/databases/%s/query" % dbid, "POST", body)
        out += r["results"]
        if not r.get("has_more"): break
        cur = r["next_cursor"]
    return out

def nupd(pid, props):
    return _nreq("https://api.notion.com/v1/pages/" + pid.replace("-", ""), "PATCH", {"properties": props})

def ncreate(dbid, props):
    return _nreq("https://api.notion.com/v1/pages", "POST", {"parent": {"database_id": dbid}, "properties": props})

# чтение свойств
def gtext(p, k):
    v = p["properties"].get(k) or {}
    a = v.get("rich_text") or v.get("title") or []
    return "".join(x.get("plain_text", "") for x in a)
def gsel(p, k):
    v = (p["properties"].get(k) or {}).get("select")
    return v["name"] if v else ""
def gdate(p, k):
    v = (p["properties"].get(k) or {}).get("date")
    return v["start"] if v else ""
def gurl(p, k):  return (p["properties"].get(k) or {}).get("url") or ""
def gmail_(p, k): return (p["properties"].get(k) or {}).get("email") or ""
def gnum(p, k):  return (p["properties"].get(k) or {}).get("number")
def grel(p, k):
    return [x["id"].replace("-", "") for x in ((p["properties"].get(k) or {}).get("relation") or [])]

# запись свойств
def stitle(s): return {"title": [{"text": {"content": s[:2000]}}]}
def stext(s):  return {"rich_text": [{"text": {"content": (s or "")[:2000]}}]}
def ssel(s):   return {"select": ({"name": s} if s else None)}
def sdate(s):  return {"date": ({"start": s} if s else None)}
def surl(s):   return {"url": (s or None)}
def srel(ids): return {"relation": [{"id": i} for i in ids]}
def scheck(b): return {"checkbox": bool(b)}

# ---------- Gmail ----------
_SVC = None
def gmail():
    global _SVC
    if _SVC is None:
        sys.path.insert(0, DIR)
        import google_api
        from googleapiclient.discovery import build
        _SVC = build("gmail", "v1", credentials=google_api.creds(), cache_discovery=False)
    return _SVC

def gsearch(q, limit=50):
    r = gmail().users().messages().list(userId="me", q=q, maxResults=limit).execute()
    return [m["id"] for m in r.get("messages", [])]

def _walk(payload, acc):
    if not payload: return
    mt = payload.get("mimeType", "")
    body = payload.get("body", {})
    if mt == "text/plain" and body.get("data"):
        acc.append(base64.urlsafe_b64decode(body["data"].encode()).decode("utf-8", "replace"))
    for part in payload.get("parts", []) or []:
        _walk(part, acc)
    if not acc and mt == "text/html" and body.get("data"):
        html = base64.urlsafe_b64decode(body["data"].encode()).decode("utf-8", "replace")
        acc.append(re.sub(r"<[^>]+>", " ", html))

def gmsg(mid):
    m = gmail().users().messages().get(userId="me", id=mid, format="full").execute()
    h = {x["name"].lower(): x["value"] for x in m["payload"].get("headers", [])}
    acc = []
    _walk(m["payload"], acc)
    return {"id": mid, "thread": m.get("threadId", ""),
            "ts": int(m.get("internalDate", "0")) // 1000,
            "frm": h.get("from", ""), "to": h.get("to", ""),
            "subject": h.get("subject", ""),
            "body": re.sub(r"[ \t]+", " ", "\n".join(acc))[:20000]}

# ---------- Telegram ----------
def tg(text):
    c = cfg()
    tok = c.get("BOT_TOKEN") or c.get("TELEGRAM_BOT_TOKEN") or c.get("TG_BOT_TOKEN")
    if not tok:
        log("TG: токен не найден в tg-bot.env — сообщение не отправлено")
        return False
    # длинный дайджест режем на части по абзацам, а не обрезаем молча
    if len(text) > 3800:
        chunks, cur = [], ""
        for para in text.split("\n\n"):
            if len(cur) + len(para) + 2 > 3800 and cur:
                chunks.append(cur); cur = para
            else:
                cur = (cur + "\n\n" + para) if cur else para
        if cur: chunks.append(cur)
        ok = True
        for k, ch in enumerate(chunks, 1):
            head = "" if len(chunks) == 1 else "(%d/%d)\n" % (k, len(chunks))
            ok = tg(head + ch) and ok
            time.sleep(1)
        return ok
    data = urllib.parse.urlencode({"chat_id": TG_CHAT, "text": text[:4000],
                                   "disable_web_page_preview": "true"}).encode()
    try:
        urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % tok, data=data, timeout=30).read()
        return True
    except Exception as e:
        log("TG ошибка: %s" % e)
        return False

# ---------- NotebookLM ----------
def nlm(*args, **kw):
    p = subprocess.run([NLM] + [str(a) for a in args], capture_output=True, text=True, timeout=kw.get("timeout", 180))
    if p.returncode != 0:
        raise RuntimeError("nlm %s -> %s" % (" ".join(args[:2]), (p.stderr or p.stdout)[:300]))
    if kw.get("raw"): return p.stdout
    try: return json.loads(p.stdout)
    except Exception: return p.stdout

def nlm_sources():
    return nlm("list", "sources", NOTEBOOK)

# ---------- трекинг ----------
TRACK_URL = {
    "UPS":       "https://www.ups.com/track?loc=en_US&tracknum=%s",
    "FedEx":     "https://www.fedex.com/fedextrack/?trknbr=%s",
    "USPS":      "https://tools.usps.com/go/TrackConfirmAction?tLabels=%s",
    "DHL":       "https://www.dhl.com/global-en/home/tracking/tracking-parcel.html?tracking-id=%s",
    "EMS":       "https://trackings.post.japanpost.jp/services/srv/search/direct?reqCodeNo1=%s&searchKind=S002&locale=en",
    "Royal Mail":"https://www.royalmail.com/track-your-item#/tracking-results/%s",
}
def track_url(carrier, num):
    return (TRACK_URL.get(carrier) or "https://t.17track.net/en#nums=%s") % num

PATTERNS = [
    ("UPS",   re.compile(r"\b(1Z[0-9A-Z]{16})\b")),
    ("USPS",  re.compile(r"\b(9[0-5]\d{20})\b")),
    ("EMS",   re.compile(r"\b([A-Z]{2}\d{9}[A-Z]{2})\b")),
    ("FedEx", re.compile(r"\b(\d{12}|\d{15})\b")),
    ("DHL",   re.compile(r"\b(\d{10})\b")),
]
SENDER_CARRIER = [
    ("ups.com", "UPS"), ("fedex.com", "FedEx"), ("usps.com", "USPS"),
    ("dhl.com", "DHL"), ("dhl.de", "DHL"), ("royalmail.com", "Royal Mail"),
    ("post.japanpost.jp", "EMS"), ("shippingeasy.com", None),
]
def sender_carrier(frm):
    f = (frm or "").lower()
    for dom, car in SENDER_CARRIER:
        if dom in f: return car
    return None

def detect_tracks(text, frm=None):
    """Возвращает [(carrier, number)]. Формат FedEx/DHL принимаем только от самого перевозчика —
    иначе 10–12 цифр ловят номера телефонов и суммы."""
    car = sender_carrier(frm)
    out, seen = [], set()
    for name, rx in PATTERNS:
        if name in ("FedEx", "DHL") and car != name:
            continue
        for m in rx.findall(text or ""):
            if m in seen: continue
            seen.add(m)
            out.append((name, m))
    return out

INV_RX = re.compile(r"\b(3[6-9]\d{5})\b")           # номера инвойсов Invaluable
def detect_invoices(text):
    return sorted(set(INV_RX.findall(text or "")))
