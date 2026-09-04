"""Iran-market car catalog with fuzzy matching for incomplete ASR.

A plain exact dictionary misses speech errors such as «سمن» for «سمند».
This module scores unique prefixes, one-letter edits, aliases, and
subsequences so a few heard letters can still resolve a unique car.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_ARABIC = str.maketrans("يكةأإآؤ", "یکهئااا")
_PUNCT = re.compile(r"[،,.!?؟:;\"'`_\-]+")
_SPACE = re.compile(r"\s+")


def fold(text: str) -> str:
    value = (text or "").strip().translate(_DIGITS).translate(_ARABIC)
    value = value.replace("‌", "").replace("ـ", "")
    value = _PUNCT.sub(" ", value)
    return _SPACE.sub(" ", value).strip().lower()


def compact(text: str) -> str:
    return fold(text).replace(" ", "")


def levenshtein(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    prev = list(range(len(right) + 1))
    for i, char in enumerate(left, start=1):
        cur = [i]
        for j, other in enumerate(right, start=1):
            ins = cur[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (char != other)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def is_subsequence(needle: str, hay: str) -> bool:
    if not needle:
        return False
    i = 0
    for char in hay:
        if char == needle[i]:
            i += 1
            if i == len(needle):
                return True
    return False


def name_score(query: str, target: str) -> int:
    q = compact(query)
    t = compact(target)
    if not q or not t:
        return 0
    if q == t:
        return 100
    if len(q) >= 3 and t.startswith(q):
        return 94
    if len(t) >= 3 and q.startswith(t):
        return 90
    if len(q) >= 3 and q in t:
        return 88
    if len(q) >= 4 and t in q:
        return 86
    distance = levenshtein(q, t)
    if distance == 1 and min(len(q), len(t)) >= 3:
        return 84
    if distance == 2 and min(len(q), len(t)) >= 5:
        return 72
    if len(q) >= 3 and is_subsequence(q, t) and len(q) >= len(t) - 2:
        return 78
    return 0


@dataclass(frozen=True)
class CarModel:
    name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class CarBrand:
    name: str
    origin: str
    aliases: tuple[str, ...]
    models: tuple[CarModel, ...] = ()


@dataclass
class VehicleHit:
    brand: str | None = None
    model: str | None = None
    origin: str = ""
    score: int = 0
    candidates: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "brand": self.brand,
            "model": self.model,
            "origin": self.origin,
            "score": self.score,
            "candidates": list(self.candidates),
        }


def _m(name: str, *aliases: str) -> CarModel:
    return CarModel(name=name, aliases=aliases)


def _b(name: str, origin: str, aliases: tuple[str, ...], *models: CarModel) -> CarBrand:
    return CarBrand(name=name, origin=origin, aliases=aliases, models=models)


CATALOG: tuple[CarBrand, ...] = (
    _b(
        "سمند",
        "ایران",
        ("سمند", "سمن", "سامند", "samand", "samandd", "semand"),
        _m("LX", "lx", "ال ایکس"),
        _m("EL", "el"),
        _m("سورن", "سورن", "soren", "سورن پلاس"),
        _m("EF7", "ef7", "ای اف هفت"),
    ),
    _b("سورن", "ایران", ("سورن", "سورن پلاس", "soren", "soren plus"), _m("پلاس", "plus", "پلاس")),
    _b(
        "دنا",
        "ایران",
        ("دنا", "دناپلاس", "dena", "dena plus"),
        _m("معمولی", "معمولی"),
        _m("پلاس", "پلاس", "plus", "دنا پلاس"),
        _m("پلاس توربو", "توربو", "turbo"),
    ),
    _b("رانا", "ایران", ("رانا", "راناپلاس", "runna", "rana"), _m("پلاس", "پلاس", "plus")),
    _b("تارا", "ایران", ("تارا", "tara", "taara"), _m("دنده‌ای", "دنده"), _m("اتومات", "اتومات", "automatic")),
    _b("ری‌را", "ایران", ("ریرا", "ری را", "ری‌را", "reera", "rira")),
    _b(
        "پژو",
        "فرانسه",
        ("پژو", "پژ", "peugeot", "peugeote", "peguete", "pegete", "peugeut"),
        _m("206", "206", "۲۰۶", "دو صد و شش"),
        _m("207", "207", "۲۰۷"),
        _m("405", "405", "۴۰۵"),
        _m("پارس", "پارس", "pars", "elx", "پارس ELX"),
        _m("2008", "2008", "۲۰۰۸"),
        _m("508", "508", "۵۰۸"),
        _m("301", "301", "۳۰۱"),
        _m("208", "208", "۲۰۸"),
        _m("407", "407", "۴۰۷"),
    ),
    _b("پارس", "ایران", ("پارس", "پژو پارس", "pars", "elx"), _m("ELX", "elx", "ال ایکس"), _m("LX", "lx")),
    _b("پراید", "ایران", ("پراید", "پراید", "pride", "saipa pride", "پراید ۱۳۱", "پراید ۱۱۱"), _m("131", "131"), _m("111", "111"), _m("141", "141")),
    _b("تیبا", "ایران", ("تیبا", "tiba", "تيبا"), _m("صندوق‌دار", "صندوق"), _m("هاچبک", "هاچبک", "۲")),
    _b("ساینا", "ایران", ("ساینا", "ساينا", "saina"), _m("اس", "s"), _m("ایکس", "x")),
    _b("کوییک", "ایران", ("کوییک", "کوئیک", "quick", "quik"), _m("آر", "r"), _m("اس", "s")),
    _b("شاهین", "ایران", ("شاهین", "شاهين", "shahin"), _m("جی", "g", "G"), _m("پلاس", "پلاس")),
    _b("اطلس", "ایران", ("اطلس", "atlas")),
    _b("سهند", "ایران", ("سهند", "sahand")),
    _b("سایپا ۱۵۱", "ایران", ("۱۵۱", "151", "سایپا ۱۵۱", "وانت ۱۵۱")),
    _b(
        "هایما",
        "چین",
        ("هایما", "haima", "هایما اس"),
        _m("S5", "s5", "اس ۵"),
        _m("S7", "s7", "اس ۷"),
        _m("8S", "8s", "۸ اس"),
    ),
    _b(
        "جک",
        "چین",
        ("جک", "jac", "جک اس"),
        _m("J4", "j4", "جی ۴"),
        _m("J5", "j5"),
        _m("J7", "j7"),
        _m("S3", "s3", "اس ۳"),
        _m("S5", "s5", "اس ۵"),
    ),
    _b(
        "کی‌ام‌سی",
        "چین",
        ("کی ام سی", "کی‌ام‌سی", "kmc", "kmc t8"),
        _m("T8", "t8", "تی ۸"),
        _m("J7", "j7"),
        _m("X5", "x5"),
    ),
    _b(
        "ام‌وی‌ام",
        "چین",
        ("ام وی ام", "ام‌وی‌ام", "mvm", "ام وی ام ایکس"),
        _m("X22", "x22", "ایکس ۲۲"),
        _m("X33", "x33", "ایکس ۳۳"),
        _m("X55", "x55", "ایکس ۵۵"),
        _m("110", "110"),
        _m("315", "315"),
        _m("530", "530"),
    ),
    _b(
        "چری",
        "چین",
        ("چری", "chery", "چری تیگو", "چری آریزو"),
        _m("آریزو ۵", "آریزو", "arrizo", "arizo 5"),
        _m("آریزو ۶", "آریزو ۶", "arrizo 6"),
        _m("تیگو ۵", "تیگو", "tiggo", "tiggo 5"),
        _m("تیگو ۷", "تیگو ۷", "tiggo 7"),
        _m("تیگو ۸", "تیگو ۸", "tiggo 8"),
    ),
    _b(
        "فونیکس",
        "چین",
        ("فونیکس", "فونیکس اف ایکس", "fownix", "phoenix"),
        _m("FX", "fx", "اف ایکس"),
        _m("آریزو ۸", "آریزو ۸", "arrizo 8"),
        _m("تیگو ۸ پرو", "تیگو ۸ پرو", "tiggo 8 pro"),
    ),
    _b("اکستریم", "چین", ("اکستریم", "exeed", "اکسید"), _m("VX", "vx"), _m("LX", "lx"), _m("TXL", "txl")),
    _b("جتور", "چین", ("جتور", "jetour", "جیتور"), _m("X70", "x70"), _m("Dashing", "dashing", "دشینگ")),
    _b("لاماری", "چین", ("لاماری", "lamari", "لاماری ایما"), _m("ایما", "ایما", "eama")),
    _b("فیدلیتی", "چین", ("فیدلیتی", "fidelity", "فیدلیتی پرایم"), _m("پرایم", "prime"), _m("پرایم ۵ نفره", "۵ نفره")),
    _b("دیگنیتی", "چین", ("دیگنیتی", "digniti", "digniti prime"), _m("پرایم", "prime"), _m("پرستیژ", "prestige")),
    _b("ریسپکت", "چین", ("ریسپکت", "respect")),
    _b("کارا", "ایران", ("کارا", "kara", "وانت کارا")),
    _b(
        "چانگان",
        "چین",
        ("چانگان", "changan"),
        _m("CS35", "cs35"),
        _m("CS55", "cs55"),
        _m("UNI-T", "unit", "یونی تی", "uni t"),
        _m("UNI-K", "unik", "یونی کی"),
    ),
    _b("هاوال", "چین", ("هاوال", "haval"), _m("H2", "h2"), _m("H6", "h6"), _m("H9", "h9")),
    _b("جیلی", "چین", ("جیلی", "geely"), _m("امگرند", "emgrand"), _m("آزکارا", "azkarra"), _m("کولری", "coolray")),
    _b("ام‌جی", "چین", ("ام جی", "ام‌جی", "mg", "ام جی"), _m("5", "5"), _m("6", "6"), _m("GS", "gs"), _m("ZS", "zs"), _m("GT", "gt")),
    _b("لیفان", "چین", ("لیفان", "lifan"), _m("620", "620"), _m("X60", "x60"), _m("820", "820")),
    _b("بسترن", "چین", ("بسترن", "besturn", "فاو بسترن"), _m("B30", "b30"), _m("B50", "b50")),
    _b("برلیانس", "چین", ("برلیانس", "brilliance"), _m("H220", "h220"), _m("H230", "h230"), _m("H330", "h330"), _m("V5", "v5")),
    _b("دانگ‌فنگ", "چین", ("دانگ فنگ", "دانگ‌فنگ", "dongfeng"), _m("H30", "h30"), _m("S30", "s30")),
    _b("زوتی", "چین", ("زوتی", "zotye"), _m("آریو", "ario")),
    _b("بایک", "چین", ("بایک", "baic"), _m("X25", "x25"), _m("X7", "x7")),
    _b("بی‌وای‌دی", "چین", ("بی وای دی", "بی‌وای‌دی", "byd"), _m("سونگ", "song"), _m("سیل", "seal"), _m("تان", "tang")),
    _b("لوکانو", "چین", ("لوکانو", "lucano", "لوکانو ال ۸"), _m("L8", "l8")),
    _b("تیگارد", "چین", ("تیگارد", "tigard"), _m("X35", "x35")),
    _b(
        "رنو",
        "فرانسه",
        ("رنو", "renault", "رنو پارس"),
        _m("تندر ۹۰", "تندر", "تندر۹۰", "l90", "تندر 90"),
        _m("ساندرو", "ساندرو", "sandero"),
        _m("مگان", "مگان", "megane"),
        _m("کپچر", "کپچر", "captur"),
        _m("داستر", "داستر", "duster"),
        _m("سیمبل", "سیمبل", "symbol"),
        _m("کولیوس", "کولیوس", "koleos"),
    ),
    _b("سیتروئن", "فرانسه", ("سیتروئن", "citroen", "سیتروين"), _m("C3", "c3"), _m("C4", "c4"), _m("C5", "c5")),
    _b(
        "تویوتا",
        "ژاپن",
        ("تویوتا", "toyota", "تويوتا"),
        _m("کمری", "کمری", "camry"),
        _m("کرولا", "کرولا", "corolla"),
        _m("یاریس", "یاریس", "yaris"),
        _m("راو۴", "rav4", "راو 4"),
        _m("پرادو", "پرادو", "prado"),
        _m("لندکروز", "لندکروز", "land cruiser", "لند کروز"),
        _m("هایلوکس", "هایلوکس", "hilux"),
        _m("اف‌جی", "fj", "اف جی"),
    ),
    _b("لکسوس", "ژاپن", ("لکسوس", "lexus"), _m("NX", "nx"), _m("RX", "rx"), _m("IS", "is"), _m("ES", "es"), _m("LX", "lx")),
    _b(
        "نیسان",
        "ژاپن",
        ("نیسان", "nissan", "نيسان"),
        _m("ماکسیما", "ماکسیما", "maxima"),
        _m("تیانا", "تیانا", "teana"),
        _m("آلتیما", "آلتیما", "altima"),
        _m("جوک", "جوک", "juke"),
        _m("قشقایی", "قشقایی", "qashqai"),
        _m("سانی", "سانی", "sunny"),
        _m("پاترول", "پاترول", "patrol"),
        _m("ایکس‌تریل", "xtrail", "ایکس تریل"),
    ),
    _b(
        "مزدا",
        "ژاپن",
        ("مزدا", "mazda"),
        _m("2", "2", "مزدا ۲"),
        _m("3", "3", "مزدا ۳", "mazda 3"),
        _m("6", "6", "مزدا ۶"),
        _m("CX-5", "cx5", "سی ایکس"),
    ),
    _b("هوندا", "ژاپن", ("هوندا", "honda"), _m("سیویک", "civic"), _m("آکورد", "accord"), _m("CR-V", "crv", "سی آر وی")),
    _b(
        "میتسوبیشی",
        "ژاپن",
        ("میتسوبیشی", "mitsubishi", "میتسوبیشي"),
        _m("لنسر", "lancer"),
        _m("اوتلندر", "outlander"),
        _m("پاجرو", "pajero"),
        _m("ASX", "asx"),
    ),
    _b("سوزوکی", "ژاپن", ("سوزوکی", "suzuki"), _m("ویتارا", "vitara", "grand vitara"), _m("جیمنی", "jimny"), _m("کیزاشی", "kizashi")),
    _b(
        "هیوندای",
        "کره",
        ("هیوندای", "هیوندا", "hyundai", "هيونداي"),
        _m("سوناتا", "سوناتا", "sonata"),
        _m("النترا", "النترا", "elantra"),
        _m("اکسنت", "اکسنت", "accent"),
        _m("توسان", "توسان", "tucson"),
        _m("سانتافه", "سانتافه", "santafe", "santa fe"),
        _m("آزرا", "آزرا", "azera"),
        _m("i20", "i20"),
        _m("i30", "i30"),
        _m("جنسیس", "genesis"),
    ),
    _b(
        "کیا",
        "کره",
        ("کیا", "kia", "کيا"),
        _m("سراتو", "سراتو", "cerato"),
        _m("اپتیما", "اپتیما", "optima"),
        _m("اسپورتیج", "اسپورتیج", "sportage"),
        _m("سورنتو", "سورنتو", "sorento"),
        _m("ریو", "ریو", "rio"),
        _m("پیکانتو", "پیکانتو", "picanto"),
    ),
    _b(
        "سانگ‌یانگ",
        "کره",
        ("سانگ یانگ", "سانگ‌یانگ", "ssangyong"),
        _m("تیوولی", "tivoli"),
        _m("کوراندو", "korando"),
        _m("رکستون", "rexton"),
        _m("اکتیون", "actyon"),
    ),
    _b(
        "بنز",
        "آلمان",
        ("بنز", "mercedes", "مرسدس", "مرسدس بنز", "benz"),
        _m("C", "c class", "سی کلاس"),
        _m("E", "e class", "ای کلاس"),
        _m("S", "s class"),
        _m("GLA", "gla"),
        _m("GLC", "glc"),
        _m("GLE", "gle"),
    ),
    _b(
        "بی‌ام‌و",
        "آلمان",
        ("بی ام و", "بی‌ام‌و", "bmw", "بی ام دبلیو"),
        _m("سری ۳", "3 series", "سری 3"),
        _m("سری ۵", "5 series", "سری 5"),
        _m("سری ۷", "7 series"),
        _m("X1", "x1"),
        _m("X3", "x3"),
        _m("X5", "x5"),
        _m("X6", "x6"),
    ),
    _b("آئودی", "آلمان", ("آئودی", "audi", "اودي"), _m("A4", "a4"), _m("A6", "a6"), _m("Q5", "q5"), _m("Q7", "q7")),
    _b("فولکس‌واگن", "آلمان", ("فولکس", "فولکس واگن", "volkswagen", "vw"), _m("گلف", "golf"), _m("پاسات", "passat"), _m("تیگوان", "tiguan"), _m("پولو", "polo")),
    _b("پورشه", "آلمان", ("پورشه", "porsche"), _m("کاین", "cayenne"), _m("ماکان", "macan"), _m("پانامرا", "panamera")),
    _b("ولوو", "سوئد", ("ولوو", "volvo"), _m("XC60", "xc60"), _m("XC90", "xc90"), _m("S60", "s60")),
    _b("فیات", "ایتالیا", ("فیات", "fiat"), _m("500", "500")),
)

_BRAND_INDEX: list[tuple[CarBrand, str]] = []
_MODEL_INDEX: list[tuple[CarBrand, CarModel, str]] = []
for _brand in CATALOG:
    for _alias in (_brand.name, *_brand.aliases):
        _BRAND_INDEX.append((_brand, fold(_alias)))
    for _model in _brand.models:
        for _alias in (_model.name, *_model.aliases):
            _MODEL_INDEX.append((_brand, _model, fold(_alias)))


def _best_unique(query: str, scored: list[tuple[int, str, Any]]) -> tuple[int, str, Any] | None:
    scored = [item for item in scored if item[0] > 0]
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], len(item[1])))
    top = scored[0]
    close = [item for item in scored if item[0] >= top[0] - 4 and item[2] != top[2]]
    # treat same resolved object as not ambiguous
    others = []
    seen = {id(top[2])}
    for item in close:
        key = id(item[2])
        if key not in seen:
            seen.add(key)
            others.append(item)
    if others and others[0][0] >= 80 and top[0] < 100:
        return None
    return top


def match_vehicle(text: str, prefer_brand: str | None = None) -> VehicleHit:
    raw = fold(text)
    if not raw:
        return VehicleHit()

    tokens = [raw, *raw.split()]
    brand_scores: list[tuple[int, str, CarBrand]] = []
    for brand, alias in _BRAND_INDEX:
        best = 0
        for token in tokens:
            best = max(best, name_score(token, alias), name_score(raw, alias))
        if best:
            brand_scores.append((best, brand.name, brand))

    model_scores: list[tuple[int, str, tuple[CarBrand, CarModel]]] = []
    for brand, model, alias in _MODEL_INDEX:
        if prefer_brand and brand.name != prefer_brand:
            continue
        best = 0
        for token in tokens:
            best = max(best, name_score(token, alias), name_score(raw, alias))
        if best:
            model_scores.append((best, f"{brand.name} {model.name}", (brand, model)))
    if prefer_brand and not model_scores:
        for brand, model, alias in _MODEL_INDEX:
            best = 0
            for token in tokens:
                best = max(best, name_score(token, alias), name_score(raw, alias))
            if best:
                model_scores.append((best, f"{brand.name} {model.name}", (brand, model)))

    brand_hit = _best_unique(raw, brand_scores)
    model_hit = _best_unique(raw, model_scores)

    result = VehicleHit()
    if brand_hit:
        result.brand = brand_hit[2].name
        result.origin = brand_hit[2].origin
        result.score = brand_hit[0]
    if model_hit:
        brand, model = model_hit[2]
        if result.brand is None or result.brand == brand.name or model_hit[0] >= (result.score or 0):
            result.brand = brand.name
            result.origin = brand.origin
            result.model = model.name
            result.score = max(result.score, model_hit[0])
        elif result.brand == brand.name:
            result.model = model.name
            result.score = max(result.score, model_hit[0])

    if result.brand and result.model is None and model_hit and model_hit[2][0].name == result.brand:
        result.model = model_hit[2][1].name

    if not result.brand:
        names = sorted({item[1] for item in brand_scores if item[0] >= 72})
        if len(names) > 1:
            result.candidates = names[:5]
        elif names:
            result.brand = names[0]
            result.score = 72
    return result


def brand_models(brand_name: str) -> list[str]:
    for brand in CATALOG:
        if brand.name == brand_name:
            return [model.name for model in brand.models]
    return []


def catalog_payload() -> list[dict[str, Any]]:
    return [
        {
            "name": brand.name,
            "origin": brand.origin,
            "aliases": list(brand.aliases),
            "models": [model.name for model in brand.models],
        }
        for brand in CATALOG
    ]
