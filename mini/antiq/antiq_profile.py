#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""antiq_profile.py — генератор PDF-досье покупки и заливка в NotebookLM.

  build <lotRef|all>      собрать PDF (в ~/.claude-assistant/antiq/pdf)
  push  <lotRef|all>      собрать и заменить источник в блокноте «Антиквариат»
  shipment <track>        пересобрать и залить все лоты одной отправки

Семь блоков: шапка · фото+факты · предмет · ссылки · доставка (общая для посылки) ·
переписка · статус и следующий шаг."""
import html, json, os, re, subprocess, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import antiq_lib as A

MON = "января февраля марта апреля мая июня июля августа сентября октября ноября декабря".split()

def rusdate(s):
    if not s: return ""
    y, m, d = s.split("-")[:3]
    return "%d %s %s" % (int(d), MON[int(m) - 1], y)
def shortdate(s):
    if not s: return ""
    y, m, d = s.split("-")[:3]
    return "%s.%s.%s" % (d, m, y)
def money(v, cur):
    if v is None: return "—"
    return ("%s,%02d %s" % ("{:,}".format(int(v)).replace(",", " "), round((v - int(v)) * 100), cur or "")).strip()
def esc(s): return html.escape(str(s)) if s is not None else ""
def gmulti(p, k):
    return [x["name"] for x in ((p["properties"].get(k) or {}).get("multi_select") or [])]

def norm_track(t):
    if not t: return ""
    m = re.match(r"\s*([A-Za-z0-9]{8,})", t)
    return m.group(1).upper() if m else ""

def plural(n):
    n = int(n); w = "лотов"
    if n % 10 == 1 and n % 100 != 11: w = "лот"
    elif n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14): w = "лота"
    return "%d %s" % (n, w)

def parse_notes(n):
    n = n or ""
    auc = addr = ""
    m = re.search(r"Аукцион:\s*(.+?)(?:\.\s*Адрес продавца|\.\s*$|$)", n)
    if m: auc = m.group(1).strip().rstrip(".")
    m = re.search(r"Адрес продавца:\s*(.+?)\.?\s*$", n)
    if m: addr = m.group(1).strip()
    rest = re.sub(r"Аукцион:\s*.+?(?=(?:\s*Адрес продавца:)|$)", "", n)
    rest = re.sub(r"Адрес продавца:\s*.+?$", "", rest).strip(" .")
    return auc, addr, re.sub(r"\s{2,}", " ", rest)

SPLIT = re.compile(r"(Provenance:|Provenance\.|Published:|Exhibited:|Scientific analysis:|Condition:)")
RU = {"Provenance": "Провенанс", "Published": "Публикации", "Exhibited": "Выставки",
      "Scientific analysis": "Экспертиза", "Condition": "Состояние"}
def split_desc(d):
    parts = SPLIT.split((d or "").strip())
    extra = [(parts[i].rstrip(":."), parts[i + 1].strip() if i + 1 < len(parts) else "")
             for i in range(1, len(parts), 2)]
    return parts[0].strip(), extra

# ---------- фото ----------
def photo_b64(ref, url):
    """Скачивает фото лота на Mini, ужимает через sips, кэширует. Возвращает base64 JPEG."""
    if not url: return ""
    jpg = os.path.join(A.IMGS, ref + ".jpg")
    if not os.path.exists(jpg):
        raw = os.path.join(A.IMGS, ref + ".raw")
        r = subprocess.run(["/usr/bin/curl", "-sSL", "--max-time", "60", "-o", raw, url], capture_output=True)
        if r.returncode != 0 or not os.path.exists(raw) or os.path.getsize(raw) < 1000:
            A.log("фото не скачалось: %s" % ref); return ""
        subprocess.run(["/usr/bin/sips", "-s", "format", "jpeg", "-Z", "900", raw, "--out", jpg],
                       capture_output=True)
        try: os.remove(raw)
        except OSError: pass
        if not os.path.exists(jpg): return ""
    import base64
    return base64.b64encode(open(jpg, "rb").read()).decode()

# ---------- данные ----------
class Data(object):
    def __init__(self):
        A.log("читаю Notion…")
        self.lots = A.nq(A.DB_LOTS)
        self.invs = {p["id"].replace("-", ""): p for p in A.nq(A.DB_INVOICES)}
        self.corr = A.nq(A.DB_CORR)
        self.by_ref = {}
        for l in self.lots:
            r = A.gtext(l, "lotRef Invaluable") or l["id"].replace("-", "")[:10].upper()
            self.by_ref[r] = l
        # группировка по отправке
        self.ship = {}
        for l in self.lots:
            ip = (A.grel(l, "Инвойс") or [None])[0]
            inv = self.invs.get(ip) if ip else None
            t = norm_track(A.gtext(inv, "Трек-номер")) if inv else ""
            key = t or ("INV:" + (ip or l["id"]))
            self.ship.setdefault(key, []).append(l)
    def inv_of(self, lot):
        ip = (A.grel(lot, "Инвойс") or [None])[0]
        return self.invs.get(ip) if ip else None
    def ship_of(self, lot):
        inv = self.inv_of(lot)
        t = norm_track(A.gtext(inv, "Трек-номер")) if inv else ""
        ip = (A.grel(lot, "Инвойс") or [None])[0]
        return self.ship.get(t or ("INV:" + (ip or lot["id"])), [lot])

def fname(D, lot):
    inv = D.inv_of(lot)
    t = A.gtext(lot, "Лот").split(": ", 1)[-1]
    t = re.sub(r'[\\/:*?"<>|]', " ", t); t = re.sub(r"\s+", " ", t).strip()
    if len(t) > 52: t = t[:52].rsplit(" ", 1)[0]
    house = re.sub(r'[\\/:*?"<>|]', " ", (A.gsel(inv, "Аукционный дом") if inv else "")).strip()
    d = shortdate(A.gdate(inv, "Дата аукциона") if inv else A.gdate(lot, "Дата аукциона"))
    return "Lot %s — %s — %s %s.pdf" % (A.gtext(lot, "Номер лота"), t, house, d)

# ---------- HTML ----------
CSS = """@page{size:A4;margin:14mm 14mm 12mm}*{box-sizing:border-box}
body{font-family:-apple-system,"Helvetica Neue",Arial,sans-serif;font-size:9.2pt;color:#1a1a1a;line-height:1.45;margin:0}
.eyebrow{font-size:7.6pt;letter-spacing:.14em;text-transform:uppercase;color:#8a7a5e}
h1{font-size:15pt;line-height:1.2;margin:2mm 0 1mm}
.sub{font-size:9pt;color:#4a4a4a;margin-bottom:4mm}
.rule{border:0;border-top:1.6pt solid #8a7a5e;margin:0 0 4mm}
h2{font-size:8.4pt;letter-spacing:.12em;text-transform:uppercase;color:#8a7a5e;border-bottom:.6pt solid #d8d2c4;padding-bottom:1mm;margin:6mm 0 2.5mm;break-after:avoid}
table{width:100%;border-collapse:collapse}
th{text-align:left;font-weight:600;color:#555;width:42mm;vertical-align:top;padding:1.1mm 3mm 1.1mm 0}
td{vertical-align:top;padding:1.1mm 0}
tr+tr th,tr+tr td{border-top:.4pt solid #eceae4}
a{color:#2a5d8f;text-decoration:none;word-break:break-all}
.top{display:flex;gap:6mm}.photo{width:66mm;flex:0 0 66mm}.photo img{width:100%;border:.6pt solid #d8d2c4}
.cap{font-size:7.2pt;color:#888;margin-top:1mm}.facts{flex:1}.facts th{width:34mm}
.desc p{margin:0 0 2mm;text-align:justify}.prov{color:#444}
.sibinv{font-weight:600;font-size:8.4pt;color:#555}
.sibgrp{margin-bottom:2mm;break-inside:avoid}
.sibgrp ul{margin:.8mm 0 0;padding-left:5mm;column-count:2;column-gap:6mm}
.sibgrp li{font-size:8.4pt;margin-bottom:.4mm;break-inside:avoid}
.corr td{font-size:8.6pt}.corr .cd{width:19mm;color:#555;white-space:nowrap}.corr .cw{width:48mm}
.dir{font-size:7.2pt;color:#999}
.next{background:#faf8f3;border-left:2.4pt solid #8a7a5e;padding:3mm 4mm}
.src{margin-top:6mm;font-size:7.4pt;color:#999;border-top:.4pt solid #eceae4;padding-top:2mm}
.badge{display:inline-block;background:#eef3ee;color:#3d6b46;border:.5pt solid #c3d7c8;padding:.6mm 2mm;border-radius:2pt;font-size:7.6pt}"""

def rows(items):
    return "".join("<tr><th>%s</th><td>%s</td></tr>" % (k, v) for k, v in items)

def build_html(D, lot):
    inv = D.inv_of(lot)
    ref = A.gtext(lot, "lotRef Invaluable")
    auc, addr, notes = parse_notes(A.gtext(inv, "Заметки") if inv else "")
    cur = A.gsel(lot, "Валюта") or (A.gsel(inv, "Валюта") if inv else "")
    title = A.gtext(lot, "Лот").split(": ", 1)[-1]
    lotno = A.gtext(lot, "Номер лота")
    house = A.gsel(inv, "Аукционный дом") if inv else ""
    date = A.gdate(inv, "Дата аукциона") if inv else A.gdate(lot, "Дата аукциона")
    img = photo_b64(ref or lotno, A.gurl(lot, "Фото"))

    contact = " · ".join(x for x in [A.gmail_(inv, "Контакт продавца") if inv else "",
                                     (inv["properties"].get("Телефон продавца") or {}).get("phone_number") or "" if inv else ""] if x)
    hcell = esc(house) + (("<br>" + esc(addr)) if addr else "") + (("<br>" + esc(contact)) if contact else "")
    invnum = A.gtext(inv, "Инвойс Invaluable") if inv else ""
    invlabel = ("#" + invnum) if invnum else "инвойс Invaluable не выставлен"
    if inv and A.gtext(inv, "Инвойс продавца"):
        invlabel += " · инвойс продавца " + esc(A.gtext(inv, "Инвойс продавца"))

    facts = [("Аукционный дом", hcell), ("Аукцион", esc(auc) or "—"), ("Дата аукциона", rusdate(date)),
             ("Инвойс", invlabel),
             ("lotRef Invaluable", esc(ref) if ref and not ref.startswith("NOINV") else "—"),
             ("Категория", esc(", ".join(gmulti(lot, "Категория")) or "—"))]

    main, extra = split_desc(A.gtext(lot, "Описание"))
    desc = "<p>%s</p>" % esc(main) + "".join(
        "<p class='prov'><b>%s.</b> %s</p>" % (RU.get(k, k), esc(v)) for k, v in extra if v)

    links = [("Лот на Invaluable", A.gurl(lot, "Ссылка на лот"))]
    if inv and A.gurl(inv, "Ссылка на инвойс Invaluable"):
        links.append(("Инвойс на Invaluable", A.gurl(inv, "Ссылка на инвойс Invaluable")))
    links += [("Фото (оригинал)", A.gurl(lot, "Фото")),
              ("Карточка в Notion", "https://app.notion.com/p/" + lot["id"].replace("-", ""))]
    lnk = "".join('<tr><th>%s</th><td><a href="%s">%s</a></td></tr>' % (esc(k), v, esc(v)) for k, v in links if v)

    m = [("Молоток", money(A.gnum(lot, "Молоток"), cur)),
         ("Итого с премией", money(A.gnum(lot, "Итого с премией"), cur))]
    if inv and A.gnum(inv, "Сумма лотов"):
        n = len(A.grel(inv, "Лоты"))
        m.append(("Сумма лотов в инвойсе", money(A.gnum(inv, "Сумма лотов"), A.gsel(inv, "Валюта") or cur) +
                  ((" (%s)" % plural(n)) if n else "")))
    pay = (A.gsel(inv, "Оплата") if inv else "") or "—"
    if inv and A.gdate(inv, "Дата оплаты"): pay += ", " + shortdate(A.gdate(inv, "Дата оплаты"))
    m += [("Оплата", esc(pay)), ("Статус лота", esc(A.gsel(lot, "Статус лота") or "—"))]
    if notes: m.append(("Примечание", esc(notes)))

    trk = A.gtext(inv, "Трек-номер") if inv else ""
    turl = (A.gurl(inv, "Ссылка на трекинг") if inv else "") or A.gurl(lot, "Ссылка на трекинг")
    sh = [("Схема", esc(A.gsel(inv, "Схема доставки") if inv else "") or "не решена"),
          ("Логист", esc(A.gtext(inv, "Логист") if inv else "") or "—"),
          ("Контакт с домом о доставке", esc(A.gsel(inv, "Контакт с домом о доставке") if inv else "") or "—"),
          ("Перевозчик", esc(A.gsel(inv, "Перевозчик") if inv else "") or "—"),
          ("Трек-номер", esc(trk) or "нет"),
          ("Проверить трек", ('<a href="%s">%s</a>' % (turl, turl)) if turl else "—"),
          ("Адрес назначения", esc(A.gsel(inv, "Адрес назначения") if inv else "") or "—"),
          ("Форвардер-получатель", esc(A.gsel(inv, "Форвардер (получатель)") if inv else "") or "—"),
          ("Статус доставки", esc(A.gsel(inv, "Статус доставки") if inv else "") or "—")]

    grp = D.ship_of(lot)
    sib = ""
    if len(grp) > 1:
        byinv = {}
        for y in grp: byinv.setdefault((A.grel(y, "Инвойс") or [""])[0], []).append(y)
        head = ("Одна отправка на два инвойса — %s:" % plural(len(grp))) if len(byinv) > 1 \
               else ("В этой же посылке — %s:" % plural(len(grp)))
        blocks = []
        for ip, ys in sorted(byinv.items(), key=lambda kv: A.gtext(D.invs.get(kv[0]), "Инвойс Invaluable") if D.invs.get(kv[0]) else ""):
            iv = D.invs.get(ip)
            lab = ("#" + A.gtext(iv, "Инвойс Invaluable")) if iv and A.gtext(iv, "Инвойс Invaluable") else (A.gtext(iv, "Инвойс") if iv else "инвойс продавца")
            items = "".join("<li>%s%s</li>" % (
                esc("%s — %s" % (A.gtext(y, "Номер лота"), A.gtext(y, "Лот").split(": ", 1)[-1][:62])),
                " <b>← этот лот</b>" if y["id"] == lot["id"] else "")
                for y in sorted(ys, key=lambda z: A.gtext(z, "Номер лота")))
            blocks.append("<div class='sibgrp'><div class='sibinv'>%s</div><ul>%s</ul></div>" % (esc(lab), items))
        sib = "<div style='margin-top:3mm'><div class='sibinv' style='margin-bottom:1.2mm'>%s</div>%s</div>" % (head, "".join(blocks))

    inv_ids = set()
    for y in grp: inv_ids |= set(A.grel(y, "Инвойс"))
    recs = [c for c in D.corr if inv_ids & set(A.grel(c, "Инвойс"))]
    recs.sort(key=lambda c: A.gdate(c, "Дата") or "")
    corr = "".join(
        "<tr><td class='cd'>%s</td><td class='cw'>%s<div class='dir'>%s%s</div></td><td>%s</td></tr>" % (
            shortdate(A.gdate(c, "Дата")), esc(A.gtext(c, "От кого") or A.gtext(c, "Тема")),
            esc(A.gsel(c, "Направление")), (" · " + esc(A.gsel(c, "Контрагент"))) if A.gsel(c, "Контрагент") else "",
            esc(A.gtext(c, "Суть") or A.gtext(c, "Тема")))
        for c in recs) or "<tr><td colspan='3' style='color:#888'>Переписки по этой отправке в доступной почте не найдено.</td></tr>"

    badge = (A.gsel(inv, "Статус доставки") if inv else "") or A.gsel(lot, "Статус лота")
    nxt = (A.gtext(inv, "Следующий шаг") if inv else "") or "—"
    ntrk = norm_track(trk)
    photo = ('<div class="photo"><img src="data:image/jpeg;base64,%s"><div class="cap">Фото аукционного дома, Invaluable</div></div>' % img) if img else ""

    return u"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><style>%s</style></head><body>
<div class="eyebrow">Профиль покупки · Лот %s · %s</div>
<h1>%s</h1>
<div class="sub">%s%s%s</div><hr class="rule">
<div class="top">%s<div class="facts"><table>%s</table></div></div>
<h2>Предмет</h2><div class="desc">%s</div>
<h2>Ссылки</h2><table>%s</table>
<h2>Деньги</h2><table>%s</table>
<h2>Доставка%s</h2><table>%s</table>%s
<h2>Переписка по доставке</h2><table class="corr">%s</table>
<h2>Статус и следующий шаг</h2><div class="next">%s</div>
<div class="src">Собрано автоматически на Mini %s из Notion (инвойсы / лоты / переписка) и Invaluable. Блок доставки и переписка общие для всех лотов одной отправки.</div>
</body></html>""" % (CSS, esc(lotno), esc(house), esc(title),
                     (esc(auc) + " · ") if auc else "", rusdate(date),
                     " · " + invlabel + ((' · <span class="badge">%s</span>' % esc(badge)) if badge else ""),
                     photo, rows(facts), desc, lnk, rows(m),
                     (" · отправка " + esc(ntrk)) if ntrk else "", rows(sh), sib, corr, esc(nxt),
                     A.today())

def build_pdf(D, lot):
    name = fname(D, lot)
    htm = os.path.join(A.PDFS, "_tmp.html")
    pdf = os.path.join(A.PDFS, name)
    open(htm, "w").write(build_html(D, lot))
    p = subprocess.run([A.CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                        "--print-to-pdf=" + pdf, "file://" + htm], capture_output=True, timeout=180)
    if not os.path.exists(pdf):
        raise RuntimeError("Chrome не собрал PDF: %s" % (p.stderr or b"")[:200])
    return pdf, name

def push(D, lot, sources=None):
    pdf, name = build_pdf(D, lot)
    if sources is None: sources = A.nlm_sources()
    old = [s for s in sources if s.get("title") == name]
    for s in old:
        try: A.nlm("delete", "source", s["id"], "-y")
        except Exception as e: A.log("не удалось удалить старый источник %s: %s" % (name, e))
    A.nlm("source", "add", A.NOTEBOOK, "--file", pdf, "--title", name, timeout=300)
    # ссылка на блокнот и имя источника в карточке лота
    A.nupd(lot["id"], {"NotebookLM": A.surl("https://notebook.google.com/notebook/" + A.NOTEBOOK),
                       "Источник в NotebookLM": A.stext(name[:-4])})
    return name

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    arg = sys.argv[2] if len(sys.argv) > 2 else "all"
    D = Data()
    if cmd == "shipment":
        targets = D.ship.get(norm_track(arg), [])
    elif arg == "all":
        targets = D.lots
    else:
        targets = [D.by_ref[r] for r in arg.split(",") if r in D.by_ref]
    if not targets:
        print("нечего делать"); return
    srcs = A.nlm_sources() if cmd == "push" or cmd == "shipment" else None
    done = 0
    for lot in targets:
        try:
            if cmd == "build":
                _, n = build_pdf(D, lot); A.log("PDF: " + n)
            else:
                n = push(D, lot, srcs); A.log("залито: " + n)
            done += 1
        except Exception as e:
            A.log("ОШИБКА %s: %s" % (A.gtext(lot, "Лот")[:40], e))
    A.log("готово: %d из %d" % (done, len(targets)))

if __name__ == "__main__":
    main()
