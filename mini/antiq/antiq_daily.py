#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""antiq_daily.py — ежедневный разбор почты по антиквариату (локально на Mini).

Читает scouer@ с прошлого прогона, находит треки/доставки/письма домов и шипперов,
обновляет инвойсы и переписку в Notion, пересобирает досье изменившихся отправок
в NotebookLM и шлёт один дайджест в Telegram.

  --dry     ничего не писать, только показать, что нашлось
  --since N начать с N дней назад (по умолчанию с чекпоинта)
Инварианты: ничего не отправляет от имени Максима, ничего не оплачивает, ничего не удаляет."""
import os, re, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import antiq_lib as A
import antiq_profile as P

DRY = "--dry" in sys.argv
MAXMSG = 80

DELIVERED_RX = re.compile(r"\b(delivered|has been delivered|new incoming|доставлен)", re.I)
SHIPPED_RX   = re.compile(r"\b(shipped|on its way|label created|tracking number|отправлен)", re.I)
STORAGE_RX   = re.compile(r"(storage|хранени|will be permanently deleted|removed from your account)", re.I)
NOT_SHIPPED  = ("Не решена", "Запрошена котировка", "Согласована — ждём отправки",
                "Ждёт оплаты доставки", "Неизвестно", "")
SHIPPER_DOMAINS = ["premierpacknship@gmail.com", "auctions1937@gmail.com", "helpdesk@pakmailstl.com",
                   "thepackengers.com", "notify.postalmate.net", "pakmailus830", "eagle"]
CARRIER_Q = ("from:ups.com OR from:fedex.com OR from:usps.com OR from:dhl.com OR from:dhl.de "
             "OR from:royalmail.com OR from:shippingeasy.com OR from:help@qwintry.com "
             "OR from:post.japanpost.jp OR from:laika.global "
             "OR from:tracking@shipstation.com OR from:shipstation.com "
             "OR from:stamps.com OR from:pirateship.com OR from:shippo.com "
             "OR from:sendcloud.com OR from:easypost.com OR from:parcelforce.com")

def dom(email):
    m = re.search(r"@([\w.\-]+)", email or "")
    return m.group(1).lower() if m else ""

def main():
    st = A.state()
    since = st.get("last_scan")
    if "--since" in sys.argv:
        since = A.now() - int(sys.argv[sys.argv.index("--since") + 1]) * 86400
    if not since:
        since = A.now() - 3 * 86400
    scan_start = A.now()
    A.log("=== ежедневный прогон, письма с %s%s ===" % (A.iso(since), " [DRY]" if DRY else ""))

    invs = A.nq(A.DB_INVOICES)
    lots = A.nq(A.DB_LOTS)
    corr = A.nq(A.DB_CORR)
    known_threads = set(A.gtext(c, "Gmail thread id") for c in corr if A.gtext(c, "Gmail thread id"))

    by_id   = {p["id"].replace("-", ""): p for p in invs}
    by_num  = {A.gtext(i, "Инвойс Invaluable"): i for i in invs if A.gtext(i, "Инвойс Invaluable")}
    by_trk  = {}
    by_dom  = {}
    for i in invs:
        t = P.norm_track(A.gtext(i, "Трек-номер"))
        if t: by_trk.setdefault(t, i)
        d = dom(A.gmail_(i, "Контакт продавца"))
        if d: by_dom.setdefault(d, []).append(i)

    def is_open(i):
        return A.gsel(i, "Статус доставки") not in ("Доставлено на склад форвардера", "Получено Максимом")

    # ---------- почта ----------
    seller_doms = sorted(set(d for d in by_dom if d))
    queries = [
        "after:%d (%s)" % (since, CARRIER_Q),
        "after:%d (from:invaluable.com OR from:bid.invaluable.com)" % since,
        "after:%d (%s)" % (since, " OR ".join("from:%s" % s for s in SHIPPER_DOMAINS)),
    ]
    if seller_doms:
        queries.append("after:%d (%s)" % (since, " OR ".join("from:%s" % d for d in seller_doms[:25])))

    ids, seen = [], set()
    for q in queries:
        try:
            for mid in A.gsearch(q, MAXMSG):
                if mid not in seen:
                    seen.add(mid); ids.append(mid)
        except Exception as e:
            A.log("поиск почты не удался (%s): %s" % (q[:40], e))
    A.log("писем к разбору: %d" % len(ids))

    changes, notes, unmatched, touched = [], [], [], {}
    lost = []
    unknown_tracks = set()
    # (арбитр 29.09) инвойсы Invaluable, которых нет в базе: карточки создаёт только
    # antiq_weekly (кабинет Invaluable), а он падает без логина с 14.09 — KCM #3976899 и
    # Showplace #3975431 (аукцион 15.09) две недели жили вне базы. Показываем в дайджесте.
    new_invs = {}

    for mid in ids[:MAXMSG]:
        try: m = A.gmsg(mid)
        except Exception as e:
            A.log("не прочитать письмо %s: %s" % (mid, e)); continue
        text = (m["subject"] or "") + "\n" + (m["body"] or "")
        frm = m["frm"]
        tracks = A.detect_tracks(text, frm)
        invnums = A.detect_invoices(text)

        inv = None
        if "invaluable.com" in frm.lower():
            for n in invnums:
                if n not in by_num and n not in new_invs:
                    new_invs[n] = (m["subject"] or "")[:70]
        for n in invnums:
            if n in by_num: inv = by_num[n]; break
        if inv is None:
            for _, t in tracks:
                if t in by_trk: inv = by_trk[t]; break
        if inv is None:
            cand = [i for i in by_dom.get(dom(frm), []) if is_open(i)]
            if len(cand) == 1: inv = cand[0]
        if inv is None:
            # письмо от стороннего сервиса рассылки (ShipStation и т.п.):
            # домен чужой, но имя дома есть в теме/отправителе/теле
            blob = (frm + " " + text[:1500]).lower()
            hit = []
            for i in invs:
                if not is_open(i): continue
                house = A.gsel(i, "Аукционный дом") or ""
                key = re.sub(r"[^a-z]", "", house.lower())[:9]
                if len(key) >= 5 and (key in re.sub(r"[^a-z]", "", blob)):
                    hit.append(i)
            if len(hit) == 1: inv = hit[0]
        extra_invs = []
        if inv is None:
            # (арбитр 27.09) письмо перевозчика без номера инвойса и без имени дома,
            # но с именем шиппера из поля «Логист» (14.09: UPS «THE UPS STORE», лоты Akiba,
            # 32 lb → ушло в «треки без инвойса», Максим 26.09: «ты не следишь»).
            # Один шиппер может везти несколько инвойсов одного дома одной посылкой —
            # тогда обновляем все.
            blob = re.sub(r"[^a-z]", "", (frm + " " + text[:2500]).lower())
            hit = []
            for i in invs:
                if not is_open(i): continue
                lg = A.gtext(i, "Логист") or ""
                key = re.sub(r"[^a-z]", "", lg.lower())[:11]
                if len(key) >= 8 and key in blob:
                    hit.append(i)
            houses = set(A.gsel(i, "Аукционный дом") for i in hit)
            if hit and len(houses) == 1:
                inv, extra_invs = hit[0], hit[1:]

        if inv is None:
            # любой несопоставленный трек — в отчёт, не только от форвардера
            for _, t in tracks:
                if t not in by_trk: unknown_tracks.add(t)
            subj_l = (m["subject"] or "").lower()
            if "removed from your account" in subj_l or "удал" in subj_l and "посылк" in subj_l:
                lost.append((m["subject"] or "")[:90])
            elif "storage" in subj_l and "expire" in subj_l:
                notes.append("склад форвардера: %s" % (m["subject"] or "")[:70])
            elif tracks or invnums or STORAGE_RX.search(text):
                unmatched.append("%s — %s" % (frm.split("<")[0].strip()[:28], (m["subject"] or "")[:60]))
            continue

        label = A.gtext(inv, "Инвойс")
        props = {}
        cur_status = A.gsel(inv, "Статус доставки")
        cur_track  = P.norm_track(A.gtext(inv, "Трек-номер"))

        # новый трек
        if tracks and not cur_track:
            car, num = tracks[0]
            props["Трек-номер"] = A.stext(num)
            props["Ссылка на трекинг"] = A.surl(A.track_url(car, num))
            if car and not A.gsel(inv, "Перевозчик"):
                props["Перевозчик"] = A.ssel(car)
            if cur_status in NOT_SHIPPED:
                props["Статус доставки"] = A.ssel("Отправлено")
            changes.append("%s: трек %s (%s)" % (label, num, car))

        # доставлено
        # «Проблема» ставится вручную и не снимается автоматически:
        # перевозчик может отрапортовать «delivered», а посылки на аккаунте нет
        if (DELIVERED_RX.search(text) and cur_status != "Доставлено на склад форвардера"
                and cur_status != "Проблема"):
            same = (not cur_track) or any(t == cur_track for _, t in tracks) or ("qwintry" in frm.lower())
            if same:
                props["Статус доставки"] = A.ssel("Доставлено на склад форвардера")
                changes.append("%s: доставлено на склад форвардера" % label)

        # дом написал — ответа нет
        d = dom(frm)
        if d in by_dom and inv in by_dom[d] and A.gsel(inv, "Контакт с домом о доставке") == "Не связывались":
            props["Контакт с домом о доставке"] = A.ssel("Дом написал — я не ответил")
            changes.append("%s: дом написал — ответа Максима нет" % label)

        if STORAGE_RX.search(text):
            notes.append("%s: письмо про хранение — %s" % (label, (m["subject"] or "")[:60]))

        if props:
            props["Последний контакт"] = A.sdate(A.iso(m["ts"])[:10])
            props["Обновлено ассистентом"] = A.sdate(A.today())
            if not DRY:
                try: A.nupd(inv["id"], props)
                except Exception as e: A.log("Notion: не обновился %s: %s" % (label, e))
            touched[inv["id"].replace("-", "")] = inv
            # (27.09) та же посылка закрывает и остальные инвойсы этого шиппера
            for x in extra_invs:
                xl = A.gtext(x, "Инвойс")
                xp = {k: v for k, v in props.items() if k != "Перевозчик" or not A.gsel(x, "Перевозчик")}
                if "Трек-номер" in xp and P.norm_track(A.gtext(x, "Трек-номер")):
                    xp.pop("Трек-номер", None); xp.pop("Ссылка на трекинг", None)
                if A.gsel(x, "Статус доставки") == "Проблема":
                    xp.pop("Статус доставки", None)
                if not DRY:
                    try: A.nupd(x["id"], xp)
                    except Exception as e: A.log("Notion: не обновился %s: %s" % (xl, e))
                touched[x["id"].replace("-", "")] = x
                changes.append("%s: та же посылка, что %s" % (xl, label))

        # запись в переписку
        if m["thread"] not in known_threads:
            known_threads.add(m["thread"])
            contact = ("Перевозчик" if A.sender_carrier(frm) else
                       "Форвардер" if "qwintry" in frm.lower() or "laika" in frm.lower() else
                       "Invaluable" if "invaluable.com" in frm.lower() else
                       "Логист-шиппер" if any(s.split("@")[0] in frm.lower() for s in SHIPPER_DOMAINS) else
                       "Аукционный дом")
            row = {"Тема": A.stitle((m["subject"] or "(без темы)")[:200]),
                   "Дата": A.sdate(A.iso(m["ts"])[:10]),
                   "Источник": A.ssel("Gmail"),
                   "Направление": A.ssel("Автоуведомление" if A.sender_carrier(frm) or "no-reply" in frm.lower() else "Входящее"),
                   "От кого": A.stext(frm[:200]),
                   "Контрагент": A.ssel(contact),
                   "Суть": A.stext(re.sub(r"\s+", " ", m["body"])[:900]),
                   "Gmail thread id": A.stext(m["thread"]),
                   "Ссылка": A.surl("https://mail.google.com/mail/u/0/#all/" + m["thread"]),
                   "Инвойс": A.srel([inv["id"]]),
                   "Требует действия": A.scheck(bool(STORAGE_RX.search(text)))}
            if not DRY:
                try: A.ncreate(A.DB_CORR, row)
                except Exception as e: A.log("Notion: переписка не записалась: %s" % e)

    # ---------- доразбор неизвестных треков ----------
    orphan = []
    for num in sorted(unknown_tracks):
        who, inv_hint = "", None
        try:
            for mid2 in A.gsearch('"%s"' % num, 8):
                m2 = A.gmsg(mid2)
                d2 = dom(m2["frm"])
                fl = m2["frm"].lower()
                if ("qwintry" in fl or "laika" in fl or "scouer@" in fl
                        or "maxim.russkikh" in fl or "russkikh" in fl):
                    continue
                who = who or (m2["frm"].split("<")[0].strip() or d2)[:40]
                for n in A.detect_invoices((m2["subject"] or "") + m2["body"]):
                    if n in by_num: inv_hint = by_num[n]; break
                if inv_hint is None:
                    cand = [i for i in by_dom.get(d2, []) if is_open(i)]
                    if len(cand) == 1: inv_hint = cand[0]
                if inv_hint: break
        except Exception as e:
            A.log("доразбор трека %s не удался: %s" % (num, e))
        if inv_hint is not None and not P.norm_track(A.gtext(inv_hint, "Трек-номер")):
            props = {"Трек-номер": A.stext(num),
                     "Ссылка на трекинг": A.surl(A.track_url("UPS" if num.startswith("1Z") else "", num)),
                     "Статус доставки": A.ssel("Доставлено на склад форвардера"),
                     "Обновлено ассистентом": A.sdate(A.today())}
            if not DRY:
                try:
                    A.nupd(inv_hint["id"], props)
                    touched[inv_hint["id"].replace("-", "")] = inv_hint
                except Exception as e:
                    A.log("Notion: не обновился %s: %s" % (A.gtext(inv_hint, "Инвойс"), e))
            changes.append("%s: трек %s принят складом (отправитель %s)" % (A.gtext(inv_hint, "Инвойс"), num, who or "?"))
        else:
            orphan.append("%s — от %s, инвойс не определён" % (num, who or "неизвестно"))

    # ---------- дедлайны хранения ----------
    import datetime
    deadlines, overdue = [], []
    LIMITS = {"Wealthier Art & Auction": (20, "$10/день"), "Hannam's Auctioneers": (10, "£5+VAT/день")}
    # (арбитр 27.09, правило Максима 26.09 08:02: «если я сам отказался — мне уже ничего
    # не требуется») — инвойс, закрытый отказом Максима, не показывать ни в «требует
    # действия», ни в сроках хранения. Признак — в «Следующем шаге»: «фактически закрыто»,
    # «закрыто отказом», «Максим отказался». Статусы в Notion при этом не трогаем.
    CLOSED_RX = re.compile(r"(фактически закрыт|закрыто отказом|максим отказал|отказался организ)", re.I)
    def closed_by_refusal(i):
        return bool(CLOSED_RX.search(A.gtext(i, "Следующий шаг") or ""))
    for i in invs:
        if not is_open(i) or closed_by_refusal(i): continue
        house = A.gsel(i, "Аукционный дом")
        if house not in LIMITS: continue
        d = A.gdate(i, "Дата аукциона")
        if not d: continue
        days = (datetime.date.today() - datetime.date(*map(int, d.split("-")[:3]))).days
        lim, fee = LIMITS[house]
        if lim - 3 <= days <= lim + 14:
            deadlines.append("%s: %d-й день после аукциона (лимит %d, дальше %s)" % (A.gtext(i, "Инвойс"), days, lim, fee))
        elif days > lim + 14:
            overdue.append("%s (%d-й день)" % (A.gtext(i, "Инвойс"), days))

    # ---------- к действию ----------
    todo = []
    for i in invs:
        if not is_open(i) or closed_by_refusal(i): continue
        st_c = A.gsel(i, "Контакт с домом о доставке")
        nxt = A.gtext(i, "Следующий шаг")
        st_d = A.gsel(i, "Статус доставки")
        # раньше сюда не попадали инвойсы с «Не требуется (дом шлёт сам)» /
        # «Согласовано», у которых доставка так и не сдвинулась (напр. ZevAntiques)
        if (st_c in ("Дом написал — я не ответил", "Не связывались")
                or st_d in ("Ждёт оплаты доставки", "Не решена",
                            "Согласована — ждём отправки", "Запрошена котировка", "Проблема")):
            days = ""
            d = A.gdate(i, "Дата аукциона")
            if d:
                try:
                    days = " [%d дн. с аукциона]" % (datetime.date.today() -
                           datetime.date(*map(int, d[:10].split("-")))).days
                except Exception: pass
            todo.append("• %s%s — %s" % (A.gtext(i, "Инвойс"), days, (nxt or st_c)[:150]))
    # самые залежавшиеся — наверх
    todo.sort(key=lambda s: -int((s.split("[")[1].split(" дн")[0]) if "[" in s else 0))

    # ---------- пересборка досье ----------
    rebuilt = []
    if touched and not DRY:
        try:
            D = P.Data()
            srcs = A.nlm_sources()
            for iid in touched:
                for lot in D.lots:
                    if iid in A.grel(lot, "Инвойс"):
                        for y in D.ship_of(lot):
                            n = P.push(D, y, srcs)
                            if n not in rebuilt: rebuilt.append(n)
                        break
        except Exception as e:
            A.log("пересборка досье не удалась: %s" % e)

    # ---------- дайджест ----------
    notes = sorted(set(notes)); unmatched = sorted(set(unmatched)); orphan = sorted(set(orphan))
    lost = sorted(set(lost))
    parts = []
    if lost:      parts.append("‼️ ПОСЫЛКИ УДАЛЕНЫ СО СКЛАДА\n" + "\n".join("• " + l for l in lost[:10]))
    if changes:   parts.append("ИЗМЕНЕНИЯ\n" + "\n".join("• " + c for c in changes[:15]))
    if deadlines: parts.append("СРОКИ ХРАНЕНИЯ\n" + "\n".join("• " + d for d in deadlines[:8]))
    if overdue:   parts.append("ДАВНО ЗА ЛИМИТОМ ХРАНЕНИЯ (%d): %s" % (len(overdue), "; ".join(overdue[:6])))
    if todo:      parts.append("ТРЕБУЕТ ДЕЙСТВИЯ\n" + "\n".join(todo[:10]))
    if notes:     parts.append("ВНИМАНИЕ\n" + "\n".join("• " + n for n in notes[:6]))
    if new_invs:  parts.append("‼️ ИНВОЙСЫ INVALUABLE, КОТОРЫХ НЕТ В БАЗЕ (%d) — недельная сверка не работает без логина\n%s"
                               % (len(new_invs), "\n".join("• #%s — %s" % (n, s) for n, s in sorted(new_invs.items())[:8])))
    if orphan:    parts.append("ТРЕКИ БЕЗ ИНВОЙСА\n" + "\n".join("• " + o for o in orphan[:8]))
    if unmatched: parts.append("НЕ СОПОСТАВЛЕНО (%d)\n%s" % (len(unmatched), "\n".join("• " + u for u in unmatched[:6])))
    if rebuilt:   parts.append("Досье обновлены: %d" % len(rebuilt))

    if parts:
        msg = "🏺 Антиквариат — сверка %s\n\n%s" % (A.today(), "\n\n".join(parts))
    else:
        msg = "🏺 Антиквариат: без изменений (%s)" % A.today()
    A.log(msg.replace("\n", " | ")[:600])
    if not DRY:
        A.tg(msg)
        st["last_scan"] = scan_start
        st["last_run_iso"] = A.iso(scan_start)
        st["last_changes"] = len(changes)
        A.save_state(st)
    else:
        print("\n----- ДАЙДЖЕСТ (dry) -----\n" + msg)

if __name__ == "__main__":
    main()
