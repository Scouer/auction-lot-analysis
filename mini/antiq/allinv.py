#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, "/Users/maxrusskikh/.claude-assistant/antiq")
from antiq_lib import *

def g(p, name):
    v = p["properties"].get(name)
    if not v: return ""
    t = v.get("type")
    if t == "date": return (v.get("date") or {}).get("start") or ""
    if t == "select": return ((v.get("select") or {}) or {}).get("name") or ""
    if t == "rich_text": return "".join(x["plain_text"] for x in v.get("rich_text", []))
    if t == "title": return "".join(x["plain_text"] for x in v.get("title", []))
    if t == "relation": return len(v.get("relation", []))
    if t == "number": return v.get("number")
    return ""

inv = nq(DB_INVOICES, {})
rows = sorted(inv, key=lambda p: g(p, "Дата аукциона") or "", reverse=True)
print("%-11s %-30s %-32s %-12s %-24s %-28s %s" % ("ДАТА","ДОМ","СТАТУС","ПЕРЕВОЗЧ","ТРЕК","АДРЕС","ЛОТ"))
for p in rows:
    print("%-11s %-30s %-32s %-12s %-24s %-28s %s" % (
        g(p,"Дата аукциона"), g(p,"Аукционный дом")[:30], g(p,"Статус доставки")[:32],
        g(p,"Перевозчик")[:12], (g(p,"Трек-номер") or "—")[:24],
        (g(p,"Адрес назначения") or "—")[:28], g(p,"Лоты")))
