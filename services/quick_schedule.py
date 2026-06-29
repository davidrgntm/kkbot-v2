from __future__ import annotations

import re
from difflib import SequenceMatcher
from datetime import datetime, date
from typing import Any

CYR_TO_LAT = str.maketrans({
    "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"yo","ж":"j","з":"z","и":"i","й":"y","к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f","х":"x","ц":"s","ч":"ch","ш":"sh","щ":"sh","ъ":"","ы":"i","ь":"","э":"e","ю":"yu","я":"ya",
    "қ":"q","ғ":"g","ҳ":"h","ў":"o","ү":"u","ӯ":"o","ӣ":"i",
    "А":"a","Б":"b","В":"v","Г":"g","Д":"d","Е":"e","Ё":"yo","Ж":"j","З":"z","И":"i","Й":"y","К":"k","Л":"l","М":"m","Н":"n","О":"o","П":"p","Р":"r","С":"s","Т":"t","У":"u","Ф":"f","Х":"x","Ц":"s","Ч":"ch","Ш":"sh","Щ":"sh","Ъ":"","Ы":"i","Ь":"","Э":"e","Ю":"yu","Я":"ya",
    "Қ":"q","Ғ":"g","Ҳ":"h","Ў":"o","Ү":"u","Ӯ":"o","Ӣ":"i",
})

SHOP_ALIAS_SEEDS = {
    "sd": ["sd", "samarkand", "samarqand", "samarkanddarvoza", "samarqanddarvoza", "самарканд", "сд"],
    "tcm": ["tcm", "tsm", "tashkentcity", "tashkentcitymall", "tashkentsiti", "toshkentcity", "toshkentsiti", "тсм", "тцм", "ташкентсити", "тошкентсити"],
    "fp": ["fp", "family", "familypark", "femily", "фп", "фемили", "фэмили"],
    "next": ["next", "nex", "jellynext", "некст"],
}

STATUS_ALIASES = {
    "day_off": ["dam", "damolish", "otgul", "otgul", "off", "dayoff", "выходной", "виходной", "dam olish"],
    "vacation": ["otpusk", "otpuska", "отпуск", "otp", "ta'til", "tatil"],
    "sick_leave": ["bolnichniy", "boln", "больничный", "касал", "kasal", "sick"],
}


def normalize_text(value: Any) -> str:
    s = str(value or "").strip().translate(CYR_TO_LAT).lower()
    s = s.replace("o'", "o").replace("g'", "g").replace("ʻ", "").replace("’", "").replace("`", "")
    return "".join(ch for ch in s if ch.isalnum())


def display_time(value: str) -> str | None:
    raw = str(value or "").strip().lower().replace(" ", "")
    raw = raw.replace(";", ":").replace(",", ":").replace(".", ":")
    if not raw:
        return None
    if ":" in raw:
        parts = raw.split(":", 1)
        h = parts[0]
        m = parts[1] if len(parts) > 1 else "00"
    else:
        if not raw.isdigit():
            return None
        if len(raw) in {3, 4}:  # 900 / 0900
            h = raw[:-2]
            m = raw[-2:]
        else:
            h = raw
            m = "00"
    try:
        hh = int(h)
        mm = int(m or 0)
    except Exception:
        return None
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return f"{hh:02d}:{mm:02d}"


def time_to_minutes(value: str) -> int:
    t = display_time(value)
    if not t:
        raise ValueError(f"Bad time: {value}")
    h, m = map(int, t.split(":"))
    total = h * 60 + m
    if h < 8:
        total += 24 * 60
    return total


def parse_date_from_text(text: str, default_date: str | None = None) -> tuple[str | None, str]:
    source = text or ""
    patterns = [
        r"(?P<y>20\d{2})[.\-/](?P<m>\d{1,2})[.\-/](?P<d>\d{1,2})",
        r"(?P<d>\d{1,2})[.\-/](?P<m>\d{1,2})(?:[.\-/](?P<y>20\d{2}|\d{2}))?",
    ]
    for pat in patterns:
        m = re.search(pat, source)
        if not m:
            continue
        gd = m.groupdict()
        y = gd.get("y")
        if y:
            y = int(y)
            if y < 100:
                y += 2000
        else:
            y = datetime.now().year
        try:
            d = int(gd["d"])
            mm = int(gd["m"])
            dt = date(y, mm, d)
            cleaned = source[: m.start()] + source[m.end() :]
            return dt.strftime("%d-%m-%Y"), cleaned
        except Exception:
            continue
    return default_date, source


TIME_RANGE_RE = re.compile(
    r"(?P<start>\b\d{1,2}(?:(?:[:.])\d{2})?\b)\s*(?:-|–|—|dan|gacha|до|to|→|>)\s*(?P<end>\b\d{1,2}(?:(?:[:.])\d{2})?\b)",
    flags=re.IGNORECASE,
)
TIME_RANGE_SPACE_RE = re.compile(
    r"(?P<start>\b\d{1,2}(?:(?:[:.])\d{2})?\b)\s+(?P<end>\b\d{1,2}(?:(?:[:.])\d{2})?\b)\s*$",
    flags=re.IGNORECASE,
)


def extract_time_range(line: str) -> tuple[str | None, str | None, str]:
    m = TIME_RANGE_RE.search(line)
    if not m:
        m = TIME_RANGE_SPACE_RE.search(line)
    if not m:
        return None, None, line
    start = display_time(m.group("start"))
    end = display_time(m.group("end"))
    rest = (line[: m.start()] + " " + line[m.end() :]).strip()
    if not start or not end:
        return None, None, line
    return start, end, rest


def shop_key_for_name(shop_name: str) -> str:
    n = normalize_text(shop_name)
    if "samarkand" in n or "samarqand" in n or "darvoza" in n:
        return "sd"
    if "tashkentcity" in n or "toshkentcity" in n or "tashkentsiti" in n or "toshkentsiti" in n or "citymall" in n:
        return "tcm"
    if "familypark" in n or "family" in n:
        return "fp"
    if "next" in n:
        return "next"
    return n


def build_shop_aliases(shops: list[str]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for shop in shops:
        if not shop:
            continue
        key = shop_key_for_name(shop)
        names = {shop, key, normalize_text(shop)}
        for seed in SHOP_ALIAS_SEEDS.get(key, []):
            names.add(seed)
        for value in names:
            n = normalize_text(value)
            if n:
                aliases[n] = shop
    return aliases


def match_shop(line: str, shops: list[str], aliases: dict[str, str]) -> tuple[str | None, float]:
    n = normalize_text(line)
    if not n:
        return None, 0.0
    if n in aliases:
        return aliases[n], 1.0
    # Lines like "SD:" or "TCM -" are normalized above; fuzzy fallback for full shop names.
    best_shop, best_score = None, 0.0
    for shop in shops:
        sn = normalize_text(shop)
        score = SequenceMatcher(None, n, sn).ratio()
        if n in sn or sn in n:
            score = max(score, 0.86)
        if score > best_score:
            best_shop, best_score = shop, score
    if best_score >= 0.78:
        return best_shop, best_score
    return None, best_score


def clean_person_text(value: str) -> str:
    s = str(value or "")
    s = re.sub(r"^[\s•\-—–:;,.]+", "", s)
    s = re.sub(r"[\s•\-—–:;,.]+$", "", s)
    s = s.replace("@ ", "@")
    return s.strip()


def staff_aliases(staff: dict) -> set[str]:
    aliases = set()
    name = str(staff.get("Имя") or staff.get("full_name") or "")
    username = str(staff.get("Username") or staff.get("username") or "")
    phone = str(staff.get("Phone") or staff.get("phone") or "")
    tid = str(staff.get("TelegramID") or staff.get("telegram_id") or "").replace(".0", "")
    for raw in [name, username, username.replace("@", ""), phone, tid]:
        n = normalize_text(raw)
        if n:
            aliases.add(n)
    # Name parts and common first-name matching.
    parts = [p for p in re.split(r"\s+", name.strip()) if p]
    for p in parts:
        n = normalize_text(p)
        if len(n) >= 3:
            aliases.add(n)
    if len(parts) >= 2:
        aliases.add(normalize_text(parts[0] + parts[1]))
    return aliases


def match_staff(query: str, staff_list: list[dict]) -> dict:
    raw = clean_person_text(query)
    if not raw:
        return {"status": "missing", "raw": query, "reason": "ism bo'sh"}
    username_mode = raw.strip().startswith("@")
    q = normalize_text(raw.replace("@", ""))
    if not q:
        return {"status": "missing", "raw": raw, "reason": "ism bo'sh"}

    q_tokens = [normalize_text(x) for x in re.split(r"\s+", raw.replace("@", " ")) if normalize_text(x)]
    candidates = []
    for st in staff_list:
        aliases = staff_aliases(st)
        if not aliases:
            continue
        best = 0.0
        exact = False
        for a in aliases:
            if not a:
                continue
            if q == a:
                best = max(best, 1.0)
                exact = True
            elif username_mode and q == a:
                best = max(best, 1.0)
            else:
                score = SequenceMatcher(None, q, a).ratio()
                for qt in q_tokens:
                    if len(qt) >= 3 and len(a) >= 3:
                        token_score = SequenceMatcher(None, qt, a).ratio()
                        if len(qt) >= 4 and len(a) >= 4 and (qt in a or a in qt):
                            token_score = max(token_score, 0.88)
                        score = max(score, token_score)
                if len(q) >= 4 and len(a) >= 4 and (q in a or a in q):
                    score = max(score, 0.88)
                best = max(best, score)
        if best > 0:
            candidates.append((best, st, exact))
    candidates.sort(key=lambda x: x[0], reverse=True)
    if not candidates:
        return {"status": "missing", "raw": raw, "reason": "bazada mos xodim topilmadi"}
    top_score, top_staff, _ = candidates[0]
    second = candidates[1][0] if len(candidates) > 1 else 0.0
    status = "ok" if top_score >= 0.84 else "warning" if top_score >= 0.66 else "missing"
    ambiguous = bool(status != "missing" and second >= 0.66 and (top_score - second) < 0.04)
    if ambiguous:
        status = "warning"
    return {
        "status": status,
        "raw": raw,
        "score": round(top_score, 3),
        "ambiguous": ambiguous,
        "telegram_id": str(top_staff.get("TelegramID") or top_staff.get("telegram_id") or "").replace(".0", ""),
        "name": str(top_staff.get("Имя") or top_staff.get("full_name") or ""),
        "role": str(top_staff.get("Роль") or top_staff.get("role") or "staff"),
        "shop_text": str(top_staff.get("Магазин") or top_staff.get("shop") or ""),
        "candidates": [
            {"name": str(st.get("Имя") or st.get("full_name") or ""), "telegram_id": str(st.get("TelegramID") or st.get("telegram_id") or ""), "score": round(score, 3)}
            for score, st, _ in candidates[:3]
        ],
    }


def detect_status(line: str) -> str | None:
    n = normalize_text(line)
    for code, arr in STATUS_ALIASES.items():
        for alias in arr:
            if normalize_text(alias) in n:
                return code
    return None


def parse_quick_schedule(text: str, staff_list: list[dict], shops: list[str], default_date: str | None = None) -> dict:
    date_str, cleaned_text = parse_date_from_text(text or "", default_date)
    shop_aliases = build_shop_aliases(shops)
    current_shop: str | None = None
    items: list[dict] = []
    unresolved: list[dict] = []
    warnings: list[str] = []
    errors: list[str] = []

    if not date_str:
        errors.append("Sana topilmadi. Avval sana tanlang yoki matnda 28.04.2026 kabi yozing.")

    for line_no, original in enumerate((cleaned_text or "").splitlines(), start=1):
        line = str(original or "").strip()
        if not line:
            continue
        # Remove repeated date snippets if they exist on their own line.
        maybe_date, remaining = parse_date_from_text(line, None)
        if maybe_date and not remaining.strip():
            date_str = maybe_date
            continue

        shop, shop_score = match_shop(line, shops, shop_aliases)
        start, end, name_part = extract_time_range(line)

        # Header line without time: shop title.
        if shop and not start and not end:
            current_shop = shop
            continue

        # Inline shop + employee: "SD Dilnavoz 10-16".
        if not shop and start and name_part:
            first = name_part.split()[0] if name_part.split() else ""
            inline_shop, _ = match_shop(first, shops, shop_aliases)
            if inline_shop:
                shop = inline_shop
                name_part = name_part[len(first) :].strip()
        elif shop and start:
            # If full line matched shop only because line starts with shop alias, remove alias from person text.
            first = name_part.split()[0] if name_part.split() else ""
            inline_shop, _ = match_shop(first, shops, shop_aliases)
            if inline_shop:
                shop = inline_shop
                name_part = name_part[len(first) :].strip()

        use_shop = shop or current_shop
        status_code = detect_status(line) if not start else None

        if not start and not status_code:
            warnings.append(f"{line_no}-qator tushunilmadi: {line}")
            continue
        if not use_shop:
            unresolved.append({"line": line_no, "raw": line, "reason": "magazin aniqlanmadi"})
            continue
        if not date_str:
            unresolved.append({"line": line_no, "raw": line, "reason": "sana aniqlanmadi"})
            continue

        person = clean_person_text(name_part if start else re.sub(r"\b(dam|dam olish|otpusk|отпуск|boln|bolnichniy|больничный|kasal|касал)\b", "", line, flags=re.I))
        m = match_staff(person, staff_list)
        if m.get("status") == "missing":
            unresolved.append({"line": line_no, "raw": line, "person": person, "shop": use_shop, "start": start, "end": end, "reason": m.get("reason", "xodim topilmadi")})
            continue
        if m.get("status") == "warning":
            warnings.append(f"{line_no}-qator: “{m['raw']}” → “{m['name']}” deb taxmin qilindi ({int(float(m.get('score',0))*100)}%).")
        if start and end:
            try:
                if time_to_minutes(end) <= time_to_minutes(start):
                    unresolved.append({"line": line_no, "raw": line, "person": person, "shop": use_shop, "start": start, "end": end, "reason": "ketish vaqti kelish vaqtidan oldin"})
                    continue
            except Exception:
                unresolved.append({"line": line_no, "raw": line, "person": person, "shop": use_shop, "start": start, "end": end, "reason": "vaqt formati noto'g'ri"})
                continue
            items.append({"date": date_str, "shop": use_shop, "tid": m["telegram_id"], "name": m["name"], "kind": "shift", "start": start, "end": end, "_raw": line, "_match_status": m.get("status"), "_score": m.get("score")})
        elif status_code:
            items.append({"date": date_str, "shop": use_shop, "tid": m["telegram_id"], "name": m["name"], "kind": "status", "status_code": status_code, "start": f"STATUS:{status_code}", "end": status_code, "_raw": line, "_match_status": m.get("status"), "_score": m.get("score")})

    # Duplicate in pasted text.
    seen = set()
    duplicates = []
    for it in items:
        key = (it.get("date"), it.get("tid"), it.get("start"), it.get("end"), it.get("status_code"))
        if key in seen:
            duplicates.append(f"{it.get('name')} — {it.get('date')} — {it.get('start')}-{it.get('end')}")
        seen.add(key)
    if duplicates:
        errors.append("Takror qator bor: " + "; ".join(duplicates[:5]))

    return {
        "date": date_str,
        "items": items,
        "unresolved": unresolved,
        "warnings": warnings,
        "errors": errors,
        "can_save": bool(items) and not unresolved and not errors,
        "source_text": text or "",
    }


def item_range_text(it: dict) -> str:
    if it.get("kind") == "status" or str(it.get("start", "")).startswith("STATUS:"):
        code = it.get("status_code") or str(it.get("start", "")).split(":", 1)[-1]
        label = {"day_off": "Dam olish", "vacation": "Otpusk", "sick_leave": "Bolnichniy"}.get(code, code)
        return f"📌 {label}"
    return f"{it.get('start')} - {it.get('end')}"


def render_quick_schedule_preview(result: dict, for_html: bool = False) -> str:
    def e(x: Any) -> str:
        import html
        return html.escape(str(x or ""), quote=True) if for_html else str(x or "")

    if for_html:
        rows = []
        for it in result.get("items", []):
            mark = "⚠️" if it.get("_match_status") == "warning" else "✅"
            rows.append(f"<tr><td>{mark}</td><td>{e(it.get('shop'))}</td><td>{e(it.get('name'))}</td><td>{e(item_range_text(it))}</td></tr>")
        unresolved = "".join(f"<li>❌ {e(x.get('raw'))} — {e(x.get('reason'))}</li>" for x in result.get("unresolved", []))
        warnings = "".join(f"<li>⚠️ {e(w)}</li>" for w in result.get("warnings", []))
        errors = "".join(f"<li>❌ {e(w)}</li>" for w in result.get("errors", []))
        return f"<h2>⚡ Preview: {e(result.get('date') or 'sana yo‘q')}</h2><table class='table'><thead><tr><th></th><th>Shop</th><th>Xodim</th><th>Vaqt</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan=4>Qator yo‘q</td></tr>'}</tbody></table><ul>{errors}{unresolved}{warnings}</ul>"

    shops: dict[str, list[dict]] = {}
    for it in result.get("items", []):
        shops.setdefault(it.get("shop") or "Noma'lum", []).append(it)
    text = f"⚡ <b>Tez grafik preview: {result.get('date') or 'sana yo‘q'}</b>\n\n"
    for shop, lst in shops.items():
        text += f"🏪 <b>{shop}</b>\n"
        for it in lst:
            mark = "⚠️" if it.get("_match_status") == "warning" else "✅"
            text += f"{mark} {it.get('name')} — {item_range_text(it)}\n"
        text += "\n"
    if result.get("errors"):
        text += "❌ <b>Xatolar:</b>\n" + "\n".join(f"• {x}" for x in result["errors"]) + "\n\n"
    if result.get("unresolved"):
        text += "❌ <b>Aniqlanmagan qatorlar:</b>\n"
        for x in result["unresolved"][:10]:
            text += f"• {x.get('raw')} — {x.get('reason')}\n"
        text += "\n"
    if result.get("warnings"):
        text += "⚠️ <b>Taxminlar:</b>\n" + "\n".join(f"• {x}" for x in result["warnings"][:10]) + "\n\n"
    if result.get("can_save"):
        text += "✅ Saqlashga tayyor."
    else:
        text += "Matnni tuzatib qayta yuboring yoki topilmagan xodim/shoplarni tekshiring."
    return text.strip()


def find_conflicts(new_items: list[dict], existing_items: list[dict]) -> list[str]:
    def conflict(a: dict, b: dict) -> bool:
        if str(a.get("date")) != str(b.get("date")):
            return False
        if str(a.get("tid") or a.get("telegram_id")) != str(b.get("tid") or b.get("telegram_id")):
            return False
        if str(a.get("start", "")).startswith("STATUS:") or str(b.get("start", "")).startswith("STATUS:"):
            return True
        try:
            return time_to_minutes(a["start"]) < time_to_minutes(b["end"]) and time_to_minutes(a["end"]) > time_to_minutes(b["start"])
        except Exception:
            return False
    conflicts = []
    all_existing = list(existing_items or [])
    for i, item in enumerate(new_items):
        for ex in all_existing:
            if conflict(item, ex):
                conflicts.append(f"{item.get('name')} uchun konflikt: {ex.get('date')} | {ex.get('shop')} | {ex.get('start')} - {ex.get('end')}")
        for j, other in enumerate(new_items):
            if i != j and conflict(item, other):
                conflicts.append(f"{item.get('name')} uchun ichki konflikt: {item.get('start')}-{item.get('end')} va {other.get('start')}-{other.get('end')}")
    out, seen = [], set()
    for c in conflicts:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out
