#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Отчёт по N последним аукционам: что выиграно, оплачено, отправлено, куда."""
import sys, json, collections
sys.path.insert(0, "/Users/maxrusskikh/.claude-assistant/antiq")
from antiq_lib import *

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5

inv = nq(DB_INVOICES, {})
lots = nq(DB_LOTS, {})
corr = nq(DB_CORR, {})

def P(p, name):
    return p["properties"].get(name)

def gd(p, name):
    v = P(p, name)
    if not v: return ""
    t = v.get("type")
    if t == "date":   return (v.get("date") or {}).get("start") or ""
    if t == "select":  return ((v.get("select") or {}) or {}).get("name") or ""
    if t == "title":   return "".join(x["plain_text"] for x in v.get("title", []))
    if t == "rich_text": return "".join(x["plain_text"] for x in v.get("rich_text", []))
    if t == "url":     return v.get("url") or ""
    if t == "number":  return v.get("number")
    if t == "email":   return v.get("email") or ""
    if t == "checkbox": return v.get("checkbox")
    if t == "relation": return [r["id"] for r in v.get("relation", [])]
    if t == "multi_select": return [x["name"] for x in v.get("multi_select", [])]
    return ""

# сортируем инвойсы по дате аукциона
rows = []
for p in inv:
    rows.append((gd(p, "Дата аукциона") or "", p))
rows.sort(key=lambda x: x[0], reverse=True)

# карта лотов по id инвойса
lots_by_inv = collections.defaultdict(list)
for l in lots:
    for rid in (gd(l, "Инвойс") or []):
        lots_by_inv[rid].append(l)

# переписка по инвойсу
corr_by_inv = collections.defaultdict(list)
for c in corr:
    for rid in (gd(c, "Инвойс") or []):
        corr_by_inv[rid].append(c)

# какие свойства вообще есть у инвойса
if rows:
    print("=== СВОЙСТВА ИНВОЙСА ===")
    print(", ".join(sorted(rows[0][1]["properties"].keys())))
    print()
if lots:
    print("=== СВОЙСТВА ЛОТА ===")
    print(", ".join(sorted(lots[0]["properties"].keys())))
    print()
if corr:
    print("=== СВОЙСТВА ПЕРЕПИСКИ ===")
    print(", ".join(sorted(corr[0]["properties"].keys())))
    print()

for date, p in rows[:N]:
    pr = p["properties"]
    print("=" * 70)
    print("AUCTION %s | %s" % (date, gd(p, "Name") or gd(p, "Название") or ""))
    for k in sorted(pr.keys()):
        v = gd(p, k)
        if v in ("", None, [], False): continue
        print("   %-34s %s" % (k + ":", v))
    ls = lots_by_inv.get(p["id"], [])
    print("   --- ЛОТЫ (%d) ---" % len(ls))
    for l in ls:
        bits = []
        for k in sorted(l["properties"].keys()):
            v = gd(l, k)
            if v in ("", None, [], False): continue
            if k in ("Инвойс",): continue
            bits.append("%s=%s" % (k, v))
        print("     * " + " | ".join(str(b)[:160] for b in bits))
    cs = corr_by_inv.get(p["id"], [])
    print("   --- ПЕРЕПИСКА (%d) ---" % len(cs))
    for c in sorted(cs, key=lambda x: gd(x, "Дата") or ""):
        print("     - %s | %s | %s" % (gd(c, "Дата"), gd(c, "Отправитель") or gd(c, "От кого"),
                                        (gd(c, "Name") or gd(c, "Тема"))[:100]))
    print()
