"""Convert spoken Persian numbers to digits for cars, km, and clock times.

ASR often writes ۲۰۶ as «دویست و شش» or «دو صفر شش». Those phrases are
turned into 206 before car matching, odometer parsing, and slot times.
"""

from __future__ import annotations

import re

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_ARABIC = str.maketrans("يكةأإآؤ", "یکهئااا")
_PUNCT = re.compile(r"[،,.!?؟:;\"'`_\-]+")

UNITS: dict[str, int] = {
    "صفر": 0,
    "یک": 1,
    "یکه": 1,
    "دو": 2,
    "سه": 3,
    "چهار": 4,
    "پنج": 5,
    "شش": 6,
    "شیش": 6,
    "هفت": 7,
    "هشت": 8,
    "نه": 9,
}

TEENS: dict[str, int] = {
    "ده": 10,
    "یازده": 11,
    "دوازده": 12,
    "سیزده": 13,
    "چهارده": 14,
    "پانزده": 15,
    "شانزده": 16,
    "هفده": 17,
    "هجده": 18,
    "نوزده": 19,
}

TENS: dict[str, int] = {
    "بیست": 20,
    "سی": 30,
    "چهل": 40,
    "پنجاه": 50,
    "شصت": 60,
    "هفتاد": 70,
    "هشتاد": 80,
    "نود": 90,
}

HUNDREDS: dict[str, int] = {
    "صد": 100,
    "یکصد": 100,
    "دویست": 200,
    "سیصد": 300,
    "چهارصد": 400,
    "پانصد": 500,
    "ششصد": 600,
    "شیشصد": 600,
    "هفتصد": 700,
    "هشتصد": 800,
    "نهصد": 900,
}

SCALES: dict[str, int] = {
    "هزار": 1000,
    "میلیون": 1_000_000,
    "میلیارد": 1_000_000_000,
}

AND = {"و", "وَ"}

INT_WORDS = {**UNITS, **TEENS, **TENS, **HUNDREDS, **SCALES}

SKIP = {
    "خودرو",
    "ماشین",
    "مدل",
    "نام",
    "کیلومتر",
    "کیلومتره",
    "ساعت",
    "وقت",
    "نوبت",
    "پژو",
}

_LEX = tuple(sorted((*INT_WORDS, *AND, *SKIP, "نیم", "ربع"), key=len, reverse=True))


def fold_fa(text: str) -> str:
    value = (text or "").strip().translate(_DIGITS).translate(_ARABIC)
    value = value.replace("‌", " ").replace("ـ", "")
    value = _PUNCT.sub(" ", value)
    return re.sub(r"\s+", " ", value).strip().lower()


def _lex_fragment(fragment: str) -> list[str]:
    out: list[str] = []
    i = 0
    length = len(fragment)
    while i < length:
        matched = next((word for word in _LEX if fragment.startswith(word, i)), None)
        if matched:
            out.append(matched)
            i += len(matched)
            continue
        if fragment[i].isdigit():
            j = i
            while j < length and fragment[j].isdigit():
                j += 1
            out.append(fragment[i:j])
            i = j
            continue
        j = i + 1
        while j < length and not fragment[j].isdigit() and not any(fragment.startswith(w, j) for w in _LEX):
            j += 1
        out.append(fragment[i:j])
        i = j
    return out


def tokenize(text: str) -> list[str]:
    folded = fold_fa(text)
    if not folded:
        return []
    tokens: list[str] = []
    for part in folded.split():
        tokens.extend(_lex_fragment(part))
    return [tok for tok in tokens if tok]


def _is_number_token(token: str) -> bool:
    return token in INT_WORDS or token in AND or token.isdigit()


def magnitude(tokens: list[str]) -> int | None:
    total = 0
    current = 0
    found = False
    for token in tokens:
        if token in AND:
            continue
        if token.isdigit():
            current += int(token)
            found = True
            continue
        if token in UNITS:
            current += UNITS[token]
            found = True
            continue
        if token in TEENS:
            current += TEENS[token]
            found = True
            continue
        if token in TENS:
            current += TENS[token]
            found = True
            continue
        if token in HUNDREDS:
            current += HUNDREDS[token]
            found = True
            continue
        if token in SCALES:
            if current == 0:
                current = 1
            current *= SCALES[token]
            total += current
            current = 0
            found = True
    if not found:
        return None
    return total + current


def digit_join(tokens: list[str]) -> int | None:
    digits: list[str] = []
    for token in tokens:
        if token in AND:
            continue
        if token in UNITS:
            digits.append(str(UNITS[token]))
        elif token.isdigit() and len(token) == 1:
            digits.append(token)
        else:
            return None
    if len(digits) < 2:
        return None
    return int("".join(digits))


def interpret_numbers(tokens: list[str]) -> list[int]:
    """Magnitude (دویست و شش → 206) plus spoken digits (دو صفر شش → 206)."""
    values: list[int] = []
    mag = magnitude(tokens)
    if mag is not None:
        values.append(mag)
    joined = digit_join(tokens)
    if joined is not None and joined not in values:
        values.append(joined)
    if joined is not None and 10 <= joined <= 99:
        padded = int(f"{str(joined)[0]}0{str(joined)[1]}")
        if padded not in values:
            values.append(padded)
    return values


def _finished_number(buf: list[str]) -> bool:
    return any(token.isdigit() or token in HUNDREDS or token in TENS or token in TEENS or token in SCALES for token in buf)


def _number_groups(tokens: list[str]) -> list[list[str]]:
    groups: list[list[str]] = []
    buf: list[str] = []
    for token in tokens:
        if token in AND and not buf:
            continue
        if token.isdigit() and len(token) >= 2 and buf and _finished_number(buf):
            groups.append(buf)
            buf = [token]
            continue
        if _is_number_token(token):
            buf.append(token)
            continue
        if buf:
            groups.append(buf)
            buf = []
    if buf:
        groups.append(buf)
    return groups


def extract_ints(text: str) -> list[int]:
    values: list[int] = []
    for group in _number_groups(tokenize(text)):
        cleaned = [tok for tok in group if tok not in AND]
        if not cleaned:
            continue
        for value in interpret_numbers(group):
            if value not in values:
                values.append(value)
    return values


def digitize_text(text: str) -> str:
    """Rewrite spoken numbers as Western digits; keep other words."""
    tokens = tokenize(text)
    if not tokens:
        return fold_fa(text)
    out: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if not buf:
            return
        values = interpret_numbers(buf)
        if values:
            scale = any(tok in SCALES for tok in buf)
            chosen = max(values) if scale else values[-1] if len(values) > 1 and values[-1] >= 100 else values[0]
            if not scale and any(v >= 100 for v in values):
                chosen = next(v for v in values if v >= 100)
            out.append(str(chosen))
        buf.clear()

    for token in tokens:
        if token in AND and not buf:
            continue
        if token.isdigit() and len(token) >= 2 and buf and _finished_number(buf):
            flush()
            buf.append(token)
            continue
        if _is_number_token(token):
            buf.append(token)
        else:
            flush()
            if token not in SKIP:
                out.append(token)
    flush()
    return " ".join(out)


def parse_int(text: str) -> int | None:
    values = extract_ints(text)
    if not values:
        folded = fold_fa(text)
        digits = re.findall(r"\d+", folded)
        if not digits:
            return None
        return int(digits[0])
    if any(word in fold_fa(text) for word in SCALES):
        return max(values)
    for value in values:
        if 100 <= value <= 9999:
            return value
    return values[0]


def parse_clock(text: str) -> str | None:
    """«نه و نیم» → 09:30, «ساعت شانزده» → 16:00."""
    folded = fold_fa(text)
    if not folded:
        return None
    minute = 0
    if "نیم" in folded:
        minute = 30
    elif "ربع" in folded:
        minute = 15
    numbers = extract_ints(re.sub(r"نیم|ربع", " ", folded))
    if not numbers:
        compact = folded.replace(":", " ").replace(".", " ")
        digits = re.findall(r"\d+", compact)
        numbers = [int(item) for item in digits]
    if not numbers:
        return None
    hour = numbers[0]
    if len(numbers) > 1 and numbers[1] in {0, 15, 30, 45} and "نیم" not in folded and "ربع" not in folded:
        minute = numbers[1]
    if any(word in folded.replace(" ", "") for word in ("عصر", "بعدازظهر", "بعدظهر")) and hour < 12:
        hour += 12
    if hour == 24:
        hour = 0
    if hour > 23:
        return None
    return f"{hour:02d}:{minute:02d}"
