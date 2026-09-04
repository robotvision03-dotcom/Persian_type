"""Hamrah Mechanic-style vehicle specs and کارشناسی checklist.

Defaults match a clean inspection so the expert only changes exceptions.
Source listing studied: https://www.hamrah-mechanic.com/cars-for-sale/toyota/corolla/3360811/
"""

from __future__ import annotations

from typing import Any

BODY_STATUSES = [
    {"value": "سالم", "label": "سالم / بدون رنگ و تعویض", "ok": True},
    {"value": "خط و خش", "label": "خط و خش", "ok": False},
    {"value": "رنگ دارد", "label": "رنگ دارد", "ok": False},
    {"value": "لیسه / قلم‌گیری", "label": "لیسه / قلم‌گیری", "ok": False},
    {"value": "فضله سوختگی", "label": "فضله سوختگی", "ok": False},
    {"value": "تعویض شده", "label": "تعویض شده", "ok": False},
    {"value": "آسیب / ضربه", "label": "آسیب / ضربه", "ok": False},
    {"value": "نیاز به تعمیر", "label": "نیاز به تعمیر", "ok": False},
]

TECH_STATUSES = [
    {"value": "سالم", "label": "سالم", "ok": True},
    {"value": "نیاز به تعمیر", "label": "نیاز به تعمیر", "ok": False},
    {"value": "تعویض شده", "label": "تعویض شده", "ok": False},
    {"value": "معیوب", "label": "معیوب", "ok": False},
    {"value": "تست نشده", "label": "تست نشده", "ok": False},
]

OPTION_STATUSES = [
    {"value": "دارد و سالم", "label": "دارد و سالم", "ok": True},
    {"value": "برقی", "label": "برقی", "ok": True},
    {"value": "مکانیکی", "label": "مکانیکی", "ok": True},
    {"value": "دارد و معیوب", "label": "دارد و معیوب", "ok": False},
    {"value": "ندارد", "label": "ندارد", "ok": False},
]

CABIN_STATUSES = [
    {"value": "سالم", "label": "سالم", "ok": True},
    {"value": "تمیز", "label": "تمیز", "ok": True},
    {"value": "خط و خش", "label": "خط و خش", "ok": False},
    {"value": "لکه / پارگی", "label": "لکه / پارگی", "ok": False},
    {"value": "بوی نامطبوع", "label": "بوی نامطبوع", "ok": False},
    {"value": "نیاز به بازسازی", "label": "نیاز به بازسازی", "ok": False},
    {"value": "تعویض شده", "label": "تعویض شده", "ok": False},
]

TREAD_OPTIONS = [
    {"value": "100 %", "label": "100 %", "ok": True},
    {"value": "90 %", "label": "90 %", "ok": True},
    {"value": "80 %", "label": "80 %", "ok": True},
    {"value": "70 %", "label": "70 %", "ok": True},
    {"value": "60 %", "label": "60 %", "ok": False},
    {"value": "50 %", "label": "50 %", "ok": False},
    {"value": "40 %", "label": "40 %", "ok": False},
    {"value": "30 %", "label": "30 %", "ok": False},
    {"value": "کمتر از ۳۰٪", "label": "کمتر از ۳۰٪", "ok": False},
]

RIM_STATUSES = [
    {"value": "سالم است", "label": "سالم است", "ok": True},
    {"value": "خط و خش", "label": "خط و خش", "ok": False},
    {"value": "تاب دارد", "label": "تاب دارد", "ok": False},
    {"value": "تعویض شده", "label": "تعویض شده", "ok": False},
    {"value": "آسیب دیده", "label": "آسیب دیده", "ok": False},
]

WEAR_STATUSES = [
    {"value": "ندارد", "label": "ندارد", "ok": True},
    {"value": "دارد", "label": "دارد", "ok": False},
]

DOC_STATUSES = [
    {"value": "دارد", "label": "دارد", "ok": True},
    {"value": "آزاد", "label": "آزاد", "ok": True},
    {"value": "تک برگی", "label": "تک برگی", "ok": True},
    {"value": "معتبر", "label": "معتبر", "ok": True},
    {"value": "وکالتی", "label": "وکالتی", "ok": True},
    {"value": "در رهن", "label": "در رهن", "ok": False},
    {"value": "ندارد", "label": "ندارد", "ok": False},
    {"value": "منقضی", "label": "منقضی", "ok": False},
    {"value": "در لحظه بازدید همراه مالک نبود", "label": "در لحظه بازدید همراه مالک نبود", "ok": False},
]

KIND_OPTIONS = {
    "body": BODY_STATUSES,
    "tech": TECH_STATUSES,
    "option": OPTION_STATUSES,
    "cabin": CABIN_STATUSES,
    "tread": TREAD_OPTIONS,
    "rim": RIM_STATUSES,
    "wear": WEAR_STATUSES,
    "document": DOC_STATUSES,
}

KIND_DEFAULT = {
    "body": "سالم",
    "tech": "سالم",
    "option": "دارد و سالم",
    "cabin": "سالم",
    "tread": "90 %",
    "rim": "سالم است",
    "wear": "ندارد",
    "document": "دارد",
}


def _items(kind: str, pairs: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"id": item_id, "label": label, "kind": kind} for item_id, label in pairs]


VEHICLE_SPEC_FIELDS = [
    {
        "key": "body_type",
        "label": "نوع بدنه",
        "options": ["سدان", "هاچ‌بک", "شاسی‌بلند", "کراس‌اوور", "وانت", "کوپه", "ون"],
    },
    {
        "key": "paint_status",
        "label": "وضعیت رنگ",
        "options": ["بدون رنگ", "رنگ دارد", "یک لکه رنگ", "چند لکه رنگ", "تمام رنگ", "تعویض قطعه"],
    },
    {
        "key": "body_condition",
        "label": "وضعیت بدنه",
        "options": ["سالم", "خط و خش", "تصادفی", "تعویض قطعه"],
    },
    {
        "key": "cabin_condition",
        "label": "وضعیت اتاق",
        "options": ["سالم", "تمیز", "خط و خش", "نیاز به بازسازی", "تعویض شده"],
    },
    {
        "key": "technical_condition",
        "label": "وضعیت فنی",
        "options": ["سالم", "نیاز به تعمیر جزئی", "نیاز به تعمیر"],
    },
    {
        "key": "color",
        "label": "رنگ بدنه",
        "options": ["سفید", "مشکی", "نقره‌ای", "خاکستری", "نوک‌مدادی", "آبی", "قرمز", "بژ", "قهوه‌ای", "سبز"],
    },
    {
        "key": "transmission",
        "label": "گیربکس",
        "options": ["اتومات", "دستی", "CVT", "تیپ‌ترونیک"],
    },
    {
        "key": "fuel_type",
        "label": "سوخت",
        "options": ["بنزین", "گازوئیل", "هیبرید", "برقی", "دوگانه‌سوز"],
    },
    {
        "key": "document_type",
        "label": "نوع سند",
        "options": ["تک برگی", "برگ سبز", "وکالتی", "شرکتی"],
    },
    {
        "key": "engine",
        "label": "شرح موتور",
        "options": ["۱۸۰۰ هیبرید", "۱۶۰۰", "۱۸۰۰", "۲۰۰۰", "۲۰۰۰ توربو", "سایر"],
        "free": True,
    },
]

INSPECTION_CATEGORIES = [
    {
        "id": "body",
        "label": "بدنه و شاسی",
        "summary_hint": "بدنه این خودرو کاملا سالم و بدون هیچ گونه تعویض و رنگ شدگی است.",
        "groups": [
            {
                "id": "doors",
                "label": "درها",
                "items": _items(
                    "body",
                    [
                        ("front_passenger_door", "درب جلو شاگرد"),
                        ("front_driver_door", "درب جلو راننده"),
                        ("rear_driver_door", "درب عقب راننده"),
                        ("rear_passenger_door", "درب عقب شاگرد"),
                        ("trunk_lid", "درب صندوق"),
                    ],
                ),
            },
            {
                "id": "fenders",
                "label": "گلگیر و رکاب",
                "items": _items(
                    "body",
                    [
                        ("front_driver_fender", "گلگیر جلو راننده"),
                        ("front_passenger_fender", "گلگیر جلو شاگرد"),
                        ("rear_driver_fender", "گلگیر عقب راننده"),
                        ("rear_passenger_fender", "گلگیر عقب شاگرد"),
                        ("driver_sill", "رکاب سمت راننده"),
                        ("passenger_sill", "رکاب سمت شاگرد"),
                    ],
                ),
            },
            {
                "id": "panels",
                "label": "کاپوت، سقف، سپر",
                "items": _items(
                    "body",
                    [
                        ("hood", "کاپوت"),
                        ("roof", "سقف"),
                        ("front_bumper", "سپر جلو"),
                        ("rear_bumper", "سپر عقب"),
                    ],
                ),
            },
            {
                "id": "pillars",
                "label": "ستون و کلاف",
                "items": _items(
                    "body",
                    [
                        ("front_passenger_pillar", "ستون جلو سمت شاگرد"),
                        ("mid_passenger_pillar", "ستون وسط شاگرد"),
                        ("rear_passenger_pillar", "ستون عقب سمت شاگرد"),
                        ("front_driver_pillar", "ستون جلو سمت راننده"),
                        ("mid_driver_pillar", "ستون وسط راننده"),
                        ("rear_driver_pillar", "ستون عقب سمت راننده"),
                        ("passenger_rail", "کلاف سمت شاگرد"),
                        ("driver_rail", "کلاف سمت راننده"),
                    ],
                ),
            },
            {
                "id": "chassis",
                "label": "شاسی و سینی",
                "items": _items(
                    "body",
                    [
                        ("front_chassis", "شاسی جلو"),
                        ("rear_chassis", "شاسی عقب"),
                        ("trunk_floor", "کف صندوق عقب"),
                        ("fan_tray", "سینی فن و جاچراغی"),
                        ("rear_tray", "سینی عقب"),
                        ("front_apron", "پالونی جلو"),
                        ("front_chassis_tip", "سرشاسی جلو"),
                        ("rear_chassis_tip", "سرشاسی عقب"),
                        ("front_chassis_flag", "پرچمی سرشاسی جلو"),
                    ],
                ),
            },
        ],
    },
    {
        "id": "cabin",
        "label": "اتاق و کابین",
        "summary_hint": "اتاق خودرو تمیز و سالم است.",
        "groups": [
            {
                "id": "cabin_main",
                "label": "وضعیت اتاق",
                "items": _items(
                    "cabin",
                    [
                        ("cabin_overall", "وضعیت کلی اتاق"),
                        ("cabin_ceiling", "سقف داخلی"),
                        ("cabin_floor", "کفپوش"),
                        ("door_cards", "رودری‌ها"),
                        ("driver_seat", "صندلی راننده"),
                        ("passenger_seat", "صندلی شاگرد"),
                        ("rear_seats", "صندلی عقب"),
                        ("dashboard", "داشبورد"),
                        ("center_console", "کنسول وسط"),
                        ("cabin_smell", "بوی اتاق"),
                    ],
                ),
            }
        ],
    },
    {
        "id": "technical",
        "label": "فنی و مکانیکی",
        "summary_hint": "وضعیت فنی خودرو سالم است.",
        "groups": [
            {
                "id": "engine_drive",
                "label": "موتور و انتقال قدرت",
                "items": _items(
                    "tech",
                    [
                        ("odometer_match", "تطبیق کارکرد با ظاهر خودرو"),
                        ("engine_performance", "وضعیت عملکرد موتور"),
                        ("engine_type", "نوع موتور خودرو"),
                        ("engine_mount", "دسته موتور"),
                        ("alternator_belt", "تسمه دینام و هرز گردها"),
                        ("gear_shifts", "تعویض دنده‌ها"),
                        ("gearbox", "گیربکس"),
                        ("gearbox_condition", "وضعیت گیربکس"),
                        ("gearbox_case", "وضعیت ظاهری گیربکس (پوسته گیربکس)"),
                        ("differential", "دیفرانسیل"),
                        ("differential_condition", "وضعیت دیفرانسیل"),
                        ("cv_axle", "پلوس"),
                    ],
                ),
            },
            {
                "id": "diag",
                "label": "دیاگ",
                "items": _items(
                    "tech",
                    [
                        ("diag_o2", "تست دیاگ سنسور اکسیژن"),
                        ("diag_rpm", "تست دیاگ سنسور دور موتور"),
                        ("diag_map", "تست دیاگ سنسور فشار هوا منیفولد"),
                        ("diag_ignition", "تست دیاگ سیستم احتراق"),
                        ("diag_tcm", "تست دیاگ کامپیوتر گیربکس"),
                    ],
                ),
            },
            {
                "id": "suspension_brake",
                "label": "جلوبندی، ترمز، فرمان",
                "items": _items(
                    "tech",
                    [
                        ("front_suspension", "سیستم جلو بندی"),
                        ("rear_suspension", "عقب بندی"),
                        ("front_driver_shock", "کمک جلو سمت راننده"),
                        ("rear_driver_shock", "کمک عقب سمت راننده"),
                        ("front_passenger_shock", "کمک جلو سمت شاگرد"),
                        ("rear_passenger_shock", "کمک عقب سمت شاگرد"),
                        ("brake_disc", "دیسک چرخ"),
                        ("brake_pads", "وضعیت لنت‌ها"),
                        ("parking_brake", "ترمز دستی (ترمز پارک)"),
                        ("abs_unit", "یونیت ABS"),
                        ("steering_box", "جعبه فرمان"),
                        ("electric_steering", "فرمان برقی"),
                    ],
                ),
            },
            {
                "id": "electrical_exhaust",
                "label": "برق و اگزوز",
                "items": _items(
                    "tech",
                    [
                        ("battery", "وضعیت باتری"),
                        ("alt_light", "چراغ دینام"),
                        ("battery_light", "چراغ باتری"),
                        ("oil_light", "چراغ روغن"),
                        ("exhaust", "منبع اگزوز"),
                        ("catalyst", "کاتالیزور"),
                    ],
                ),
            },
        ],
    },
    {
        "id": "options",
        "label": "آپشن و تجهیزات",
        "summary_hint": "تجهیزات خودرو سالم و کامل است.",
        "groups": [
            {
                "id": "safety_adas",
                "label": "ایمنی و رادار",
                "items": _items(
                    "option",
                    [
                        ("front_park_sensor", "سنسور فاصله جلو"),
                        ("rear_park_sensor", "سنسور فاصله عقب"),
                        ("rear_camera", "دوربین دنده عقب"),
                        ("lane_radar", "رادار بین خطوط"),
                        ("sign_radar", "رادار تابلو خوان"),
                        ("pedestrian_radar", "رادار تشخیص عابر پیاده"),
                        ("acc_radar", "رادار کروز کنترل (تشخیص فاصله طولی)"),
                        ("side_radar", "رادار جانبی (تشخیص فاصله جانبی)"),
                        ("blind_spot", "رادار نقطه کور"),
                        ("airbag_diag", "تست دیاگ ایربگ"),
                        ("seatbelt", "کمربند ایمنی"),
                    ],
                ),
            },
            {
                "id": "lights_glass",
                "label": "شیشه، چراغ، برف‌پاک‌کن",
                "items": _items(
                    "option",
                    [
                        ("windshield", "شیشه جلو"),
                        ("rear_glass", "شیشه عقب"),
                        ("driver_front_window", "شیشه جلو راننده"),
                        ("driver_rear_window", "شیشه عقب راننده"),
                        ("passenger_front_window", "شیشه جلو شاگرد"),
                        ("passenger_rear_window", "شیشه عقب شاگرد"),
                        ("side_mirrors", "آینه‌های بغل (برقی-مکانیکی)"),
                        ("headlights", "چراغ جلو"),
                        ("taillights", "چراغ خطر عقب"),
                        ("front_fog", "مه‌شکن جلو"),
                        ("rear_fog", "مه‌شکن عقب"),
                        ("auto_light", "سیستم روشنایی اتومات (اتولایت)"),
                        ("wipers", "برف‌پاک‌کن جلو"),
                        ("washer", "آب‌پاش برف‌پاک‌کن"),
                        ("rain_sensor", "سنسور باران"),
                        ("rear_defrost", "گرم‌کن شیشه عقب"),
                    ],
                ),
            },
            {
                "id": "comfort",
                "label": "کابین و راحتی",
                "items": _items(
                    "option",
                    [
                        ("ac", "سیستم تهویه"),
                        ("driver_seat_adj", "تنظیمات صندلی راننده (برقی-مکانیکی)"),
                        ("passenger_seat_adj", "تنظیمات صندلی سرنشین جلو (برقی-مکانیکی)"),
                        ("seat_cover", "روکش صندلی‌ها"),
                        ("multimedia", "مولتی‌مدیا و سیستم صوتی"),
                        ("dash_condition", "وضعیت داشبورد"),
                        ("wheel_audio", "کلیدهای کنترل صوتی روی فرمان"),
                        ("steering_condition", "وضعیت غربیلک فرمان"),
                        ("steering_adj", "تنظیم محل قرارگیری فرمان (برقی-مکانیکی)"),
                        ("central_lock", "قفل مرکزی"),
                        ("cruise", "کروز کنترل"),
                        ("drive_mode", "کلیدهای تنظیم حالات رانندگی (درایو مد)"),
                        ("power_tailgate", "عملکرد بازکننده درب صندوق (برقی-مکانیکی)"),
                        ("sunroof", "سیستم سانروف"),
                        ("keyless", "کی‌لس (keyless)"),
                        ("auto_hold", "اتوهلد"),
                        ("start_stop", "سیستم استارت/استاپ"),
                        ("coolbox", "کول‌باکس"),
                        ("horn", "بوق"),
                        ("jack", "جک و آچار چرخ"),
                        ("fuel_door", "در بازکن باک بنزین"),
                        ("tpms", "سنسور کنترل فشار باد لاستیک"),
                    ],
                ),
            },
        ],
    },
    {
        "id": "tires",
        "label": "رینگ و لاستیک",
        "summary_hint": "رینگ‌ها سالم و آج لاستیک مناسب است.",
        "groups": [
            {
                "id": "tread",
                "label": "آج لاستیک",
                "items": _items(
                    "tread",
                    [
                        ("fl_tread", "میزان آج لاستیک جلو سمت راننده"),
                        ("fr_tread", "میزان آج لاستیک جلو سمت شاگرد"),
                        ("rl_tread", "میزان آج لاستیک عقب سمت راننده"),
                        ("rr_tread", "میزان آج لاستیک عقب سمت شاگرد"),
                        ("spare_tread", "لاستیک زاپاس"),
                    ],
                ),
            },
            {
                "id": "rims",
                "label": "وضعیت رینگ",
                "items": _items(
                    "rim",
                    [
                        ("fl_rim", "وضعیت ظاهری رینگ جلو راننده"),
                        ("fr_rim", "وضعیت ظاهری رینگ جلو شاگرد"),
                        ("rl_rim", "وضعیت ظاهری رینگ عقب راننده"),
                        ("rr_rim", "وضعیت ظاهری رینگ عقب شاگرد"),
                    ],
                ),
            },
            {
                "id": "wear",
                "label": "لاستیک‌سایی",
                "items": _items(
                    "wear",
                    [
                        ("front_wear", "لاستیک‌سایی چرخ‌های جلو"),
                        ("rear_wear", "لاستیک‌سایی چرخ‌های عقب"),
                    ],
                ),
            },
        ],
    },
    {
        "id": "documents",
        "label": "اسناد و مدارک",
        "summary_hint": "مدارک خودرو کامل است.",
        "groups": [
            {
                "id": "docs",
                "label": "مدارک",
                "items": _items(
                    "document",
                    [
                        ("third_party_insurance", "مانده بیمه شخص ثالث"),
                        ("title_type", "نوع سند"),
                        ("green_sheet", "برگه سبز"),
                        ("car_card", "کارت ماشین"),
                        ("vehicle_deed", "سند خودرو"),
                        ("company_deed", "سند کمپانی"),
                        ("tech_inspection", "معاینه فنی"),
                        ("warranty", "گارانتی"),
                    ],
                ),
            }
        ],
    },
]

BODY_DIAGRAM_PANELS = [
    "hood",
    "roof",
    "trunk_lid",
    "front_driver_door",
    "rear_driver_door",
    "front_passenger_door",
    "rear_passenger_door",
    "front_bumper",
    "rear_bumper",
    "front_chassis",
    "rear_chassis",
]


def flatten_items(category: dict[str, Any]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for group in category.get("groups") or []:
        items.extend(group.get("items") or [])
    return items


def inspection_catalog() -> dict[str, Any]:
    categories = []
    for category in INSPECTION_CATEGORIES:
        items = flatten_items(category)
        categories.append(
            {
                "id": category["id"],
                "label": category["label"],
                "summary_hint": category["summary_hint"],
                "groups": category["groups"],
                "items": items,
                "item_count": len(items),
            }
        )
    return {
        "source": "hamrah-mechanic.com/cars-for-sale/toyota/corolla/3360811",
        "vehicle_fields": VEHICLE_SPEC_FIELDS,
        "kinds": KIND_OPTIONS,
        "defaults": KIND_DEFAULT,
        "categories": categories,
        "body_diagram": BODY_DIAGRAM_PANELS,
    }


def default_item_status(kind: str) -> str:
    return KIND_DEFAULT.get(kind, "سالم")


def status_is_ok(kind: str, value: str) -> bool:
    for option in KIND_OPTIONS.get(kind, []):
        if option["value"] == value:
            return bool(option.get("ok"))
    return True


def empty_report() -> dict[str, Any]:
    categories: dict[str, Any] = {}
    for category in INSPECTION_CATEGORIES:
        items = {}
        for item in flatten_items(category):
            items[item["id"]] = {"status": default_item_status(item["kind"]), "note": ""}
        categories[category["id"]] = {
            "id": category["id"],
            "label": category["label"],
            "score": 10,
            "summary": category["summary_hint"],
            "items": items,
        }
    return {
        "summary": "بدنه این خودرو کاملا سالم و بدون هیچ گونه تعویض و رنگ شدگی است.",
        "strengths": [],
        "categories": categories,
    }


def _as_item(value: Any, kind: str) -> dict[str, str]:
    if isinstance(value, dict):
        status = str(value.get("status") or default_item_status(kind))
        note = str(value.get("note") or "")
        return {"status": status, "note": note}
    if value:
        return {"status": str(value), "note": ""}
    return {"status": default_item_status(kind), "note": ""}


def normalize_report(raw: dict[str, Any] | None) -> dict[str, Any]:
    base = empty_report()
    incoming = raw if isinstance(raw, dict) else {}
    incoming_cats = incoming.get("categories") if isinstance(incoming.get("categories"), dict) else {}
    for category in INSPECTION_CATEGORIES:
        cat_id = category["id"]
        incoming_cat = incoming_cats.get(cat_id) if isinstance(incoming_cats.get(cat_id), dict) else {}
        incoming_items = incoming_cat.get("items") if isinstance(incoming_cat.get("items"), dict) else {}
        scored = []
        for item in flatten_items(category):
            merged = _as_item(incoming_items.get(item["id"]), item["kind"])
            base["categories"][cat_id]["items"][item["id"]] = merged
            scored.append(1 if status_is_ok(item["kind"], merged["status"]) else 0)
        total = len(scored) or 1
        score = max(1, round(10 * sum(scored) / total)) if scored else 10
        if sum(scored) == total:
            score = 10
        base["categories"][cat_id]["score"] = score
        hint = incoming_cat.get("summary") or category["summary_hint"]
        if sum(scored) != total:
            issues = [
                item["label"]
                for item in flatten_items(category)
                if not status_is_ok(item["kind"], base["categories"][cat_id]["items"][item["id"]]["status"])
            ]
            hint = "موارد نیازمند توجه: " + "، ".join(issues[:6])
            if len(issues) > 6:
                hint += "…"
        base["categories"][cat_id]["summary"] = str(hint)
    summary = str(incoming.get("summary") or "").strip()
    if not summary:
        body = base["categories"]["body"]
        summary = body["summary"] if body["score"] == 10 else body["summary"]
    strengths = incoming.get("strengths") or []
    if isinstance(strengths, str):
        strengths = [part.strip() for part in strengths.replace("\n", "،").split("،") if part.strip()]
    if not isinstance(strengths, list):
        strengths = []
    base["summary"] = summary
    base["strengths"] = [str(item).strip() for item in strengths if str(item).strip()]
    return base


def public_report(report: dict[str, Any] | None) -> dict[str, Any]:
    normalized = normalize_report(report)
    categories = []
    for category in INSPECTION_CATEGORIES:
        saved = normalized["categories"][category["id"]]
        items = []
        for item in flatten_items(category):
            finding = saved["items"][item["id"]]
            items.append(
                {
                    "id": item["id"],
                    "label": item["label"],
                    "kind": item["kind"],
                    "status": finding["status"],
                    "note": finding["note"],
                    "ok": status_is_ok(item["kind"], finding["status"]),
                    "group": next(
                        group["id"]
                        for group in category["groups"]
                        if item["id"] in {row["id"] for row in group["items"]}
                    ),
                }
            )
        categories.append(
            {
                "id": category["id"],
                "label": category["label"],
                "score": saved["score"],
                "summary": saved["summary"],
                "items": items,
                "groups": [
                    {
                        "id": group["id"],
                        "label": group["label"],
                        "items": [row for row in items if row["id"] in {item["id"] for item in group["items"]}],
                    }
                    for group in category["groups"]
                ],
            }
        )
    return {
        "summary": normalized["summary"],
        "strengths": normalized["strengths"],
        "categories": categories,
    }
