#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, re, time, datetime
sys.path.insert(0, "/Users/maxrusskikh/.claude-assistant/antiq")
from antiq_lib import *
import datetime as _dt

SVC = gmail()

def hdrs(mid):
    for attempt in range(6):
        try:
            m = SVC.users().messages().get(userId="me", id=mid, format="metadata",
                    metadataHeaders=["From", "Subject", "Date"]).execute()
            h = {x["name"].lower(): x["value"] for x in m["payload"].get("headers", [])}
            return {"frm": h.get("from", ""), "subject": h.get("subject", ""),
                    "ts": int(m.get("internalDate", "0")) // 1000, "thread": m.get("threadId", ""),
                    "snippet": m.get("snippet", "")}
        except Exception as e:
            if "rateLimit" in str(e) or "Quota" in str(e):
                time.sleep(8); continue
            return None
    return None

def srch(q, limit=25):
    for attempt in range(6):
        try:
            r = SVC.users().messages().list(userId="me", q=q, maxResults=limit).execute()
            return [m["id"] for m in r.get("messages", [])]
        except Exception as e:
            if "rateLimit" in str(e) or "Quota" in str(e):
                time.sleep(8); continue
            print("  ERR", str(e)[:120]); return []
    return []

QUERIES = [
 ("ZEV",        'after:2026/08/05 (from:zevantiques.com OR to:zevantiques.com OR subject:D1720 OR subject:2322)'),
 ("ZEV-PAY",    'after:2026/08/05 (zelle OR "money transfer" OR "payment sent" OR wise OR remitly) '),
 ("LUBAN",      'after:2026/08/25 (lubanantique OR "Luban")'),
 ("MEGA",       'after:2026/08/20 (mega-auction OR "Mega International" OR megaturbo)'),
 ("WEALTHIER",  'after:2026/08/20 (wealthierart OR premierpacknship OR "Premier Pack" OR "release form")'),
 ("TOISHINSEI", 'after:2026/08/10 (toishinsei OR CN132599597JP)'),
 ("AKIBA",      'after:2026/08/28 (akiba OR auctions1937)'),
 ("SHIPPED",    'after:2026/08/25 (subject:shipped OR subject:tracking OR subject:"on its way" OR subject:delivered)'),
 ("QWINTRY",    'after:2026/08/20 (from:qwintry.com OR subject:qwintry OR subject:"new incoming")'),
 ("UPS-DHL",    'after:2026/08/20 (from:ups.com OR from:dhl.com OR from:usps.com OR from:fedex.com)'),
]
for tag, q in QUERIES:
    print("#" * 70)
    print("### %s" % tag)
    ids = srch(q)
    seen = set()
    for mid in ids:
        h = hdrs(mid)
        time.sleep(0.35)
        if not h: continue
        key = (h["subject"], h["frm"])
        if key in seen: continue
        seen.add(key)
        dt = _dt.datetime.fromtimestamp(h["ts"]).strftime("%d.%m %H:%M")
        tr = set()
        blob = h["subject"] + " " + h["snippet"]
        for pat in [r'\b1Z[0-9A-Z]{16}\b', r'\b[A-Z]{2}\d{9}[A-Z]{2}\b', r'\b9[24]\d{20}\b', r'\b\d{12}\b']:
            tr |= set(re.findall(pat, blob))
        print("  [%s] %-38s | %s" % (dt, h["frm"][:38], h["subject"][:80]))
        if tr: print("        >>TRACK: " + ", ".join(sorted(tr)))
        print("        thr=%s :: %s" % (h["thread"], h["snippet"][:150].replace("\n", " ")))
    print()
