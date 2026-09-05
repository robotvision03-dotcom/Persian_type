"""Send calendar and follow-up texts from the software WhatsApp line."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

from .booking import DEFAULT_WHATSAPP, durable_file, whatsapp_digits

SOFTWARE_WHATSAPP = DEFAULT_WHATSAPP


def config_path() -> Path:
    return durable_file("whatsapp.json")


def software_number() -> str:
    raw = os.environ.get("WHATSAPP_FROM") or load_config().get("from") or SOFTWARE_WHATSAPP
    digits = whatsapp_digits(str(raw))
    return f"+{digits}" if digits else SOFTWARE_WHATSAPP


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _cfg(*names: str) -> str:
    file_cfg = load_config()
    for name in names:
        value = os.environ.get(name) or file_cfg.get(name) or ""
        if str(value).strip():
            return str(value).strip()
    return ""


def public_origin(origin: str = "", invite: dict[str, Any] | None = None) -> str:
    env = (os.environ.get("PUBLIC_BASE_URL") or load_config().get("public_base_url") or "").strip()
    if env:
        return str(env).rstrip("/")
    if origin:
        return origin.rstrip("/")
    if invite and invite.get("public_origin"):
        return str(invite["public_origin"]).rstrip("/")
    return "http://127.0.0.1:8000"


def calendar_text(invite: dict[str, Any], calendar_url: str) -> str:
    return (
        f"سلام {invite['customer_name']} عزیز\n"
        f"برای بازدید و خرید {invite['car_name']} {invite['car_model']} "
        f"این لینک تقویم نوبت‌های خالی است:\n{calendar_url}\n"
        "لطفاً وقت آزاد را انتخاب کنید و ثبت را تأیید کنید."
    )


def reminder_text(invite: dict[str, Any], calendar_url: str) -> str:
    return (
        f"سلام {invite['customer_name']} عزیز\n"
        "یادآوری نوبت بازدید: هنوز وقت خود را از تقویم انتخاب و تأیید نکرده‌اید.\n"
        f"برای {invite['car_name']} {invite['car_model']}:\n"
        f"{calendar_url}\n"
        "لطفاً وقت آزاد را انتخاب کنید و ثبت را تأیید کنید."
    )


def attach_message(
    invite: dict[str, Any] | None,
    origin: str = "",
    kind: str = "invite",
) -> dict[str, Any] | None:
    if not invite:
        return None
    extra = dict(invite)
    calendar_url = f"{public_origin(origin, extra)}{extra.get('calendar_path') or '/book/' + extra['token']}"
    extra["from_number"] = software_number()
    extra["calendar_url"] = calendar_url
    extra["call_url"] = f"tel:{extra.get('phone') or software_number()}"
    if kind == "reminder":
        extra["whatsapp_text"] = reminder_text(extra, calendar_url)
        extra["reminder_number"] = int(extra.get("reminder_count") or 0) + 1
    else:
        extra["whatsapp_text"] = calendar_text(extra, calendar_url)
    return extra


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> tuple[bool, str]:
    raw = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=raw, method="POST")
    request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    return _read_response(request)


def _post_form(url: str, payload: dict[str, Any]) -> tuple[bool, str]:
    raw = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(url, data=raw, method="POST")
    return _read_response(request)


_web_jobs: queue.Queue[dict[str, Any]] = queue.Queue()
_web_worker_started = False
_web_lock = threading.Lock()


def _can_use_whatsapp_web() -> bool:
    if os.environ.get("DISABLE_WHATSAPP_WEB") == "1":
        return False
    if os.environ.get("WHATSAPP_WEB") == "0":
        return False
    if os.environ.get("WHATSAPP_WEB") == "1":
        return True
    return os.name == "nt"


def web_send_url(phone: str, text: str) -> str:
    digits = whatsapp_digits(phone)
    encoded = urllib.parse.quote(text)
    return (
        "https://web.whatsapp.com/send/"
        f"?phone={digits}&text={encoded}&type=phone_number&app_absent=0"
    )


def _browser_candidates() -> list[str]:
    paths = [
        os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    seen: list[str] = []
    for path in paths:
        if path and path not in seen and os.path.isfile(path):
            seen.append(path)
    return seen


def _open_whatsapp_tab(url: str) -> str:
    if os.name == "nt":
        for browser in _browser_candidates():
            subprocess.Popen([browser, "--new-tab", url], close_fds=True)
            return browser
        os.startfile(url)  # type: ignore[attr-defined]
        return "startfile"
    webbrowser.open(url, new=2)
    return "webbrowser"


def _focus_whatsapp_window() -> None:
    if os.name != "nt":
        return
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "$w = New-Object -ComObject WScript.Shell; "
                    "foreach ($title in @('WhatsApp', 'Chrome', 'Edge')) { "
                    "if ($w.AppActivate($title)) { break } }"
                ),
            ],
            timeout=8,
            capture_output=True,
            check=False,
        )
    except Exception:
        return


def _press_send() -> None:
    import pyautogui

    pyautogui.FAILSAFE = False
    _focus_whatsapp_window()
    time.sleep(0.5)
    for _ in range(3):
        pyautogui.press("enter")
        time.sleep(1.0)


def send_via_whatsapp_web(to: str, text: str) -> dict[str, Any]:
    dest = whatsapp_digits(to)
    source = whatsapp_digits(software_number())
    result = {
        "from": f"+{source}" if source else software_number(),
        "to": f"+{dest}" if dest else "",
        "provider": "whatsapp-web",
        "ok": False,
        "error": "",
        "queued": False,
    }
    wait_s = max(6, int(os.environ.get("WHATSAPP_WEB_WAIT") or 15))
    try:
        with _web_lock:
            opened = _open_whatsapp_tab(web_send_url(dest, text))
            time.sleep(wait_s)
            _press_send()
    except ImportError:
        result["error"] = "برای ارسال از واتساپ وب، run.bat را دوباره اجرا کنید تا pyautogui نصب شود."
        return result
    except Exception as extra:
        result["error"] = f"واتساپ وب باز نشد: {extra}"
        return result
    result["ok"] = True
    result["browser"] = opened
    return result


def _web_worker() -> None:
    while True:
        job = _web_jobs.get()
        try:
            result = send_via_whatsapp_web(str(job["to"]), str(job["text"]))
            token = job.get("token")
            if token:
                from .booking import record_invite_send

                record_invite_send(
                    str(token),
                    str(job.get("origin") or ""),
                    result,
                    db_path=job.get("db_path"),
                )
        except Exception:
            continue
        finally:
            _web_jobs.task_done()


def _ensure_web_worker() -> None:
    global _web_worker_started
    if _web_worker_started:
        return
    _web_worker_started = True
    threading.Thread(target=_web_worker, name="whatsapp-web-send", daemon=True).start()


def enqueue_whatsapp_web(
    to: str,
    text: str,
    token: str = "",
    origin: str = "",
    db_path: Path | None = None,
) -> dict[str, Any]:
    dest = whatsapp_digits(to)
    source = whatsapp_digits(software_number())
    _ensure_web_worker()
    _web_jobs.put(
        {"to": dest, "text": text, "token": token, "origin": origin, "db_path": db_path}
    )
    return {
        "from": f"+{source}" if source else software_number(),
        "to": f"+{dest}" if dest else "",
        "provider": "whatsapp-web",
        "ok": True,
        "error": "",
        "queued": True,
    }


def _read_response(request: urllib.request.Request) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8", errors="replace")
            ok = 200 <= getattr(response, "status", 200) < 300
            return ok, body
    except urllib.error.HTTPError as extra:
        err = extra.read().decode("utf-8", errors="replace")
        return False, err or str(extra)
    except Exception as extra:
        return False, str(extra)


def send_text(
    to: str | None,
    text: str,
    token: str = "",
    origin: str = "",
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Push a WhatsApp text from the software line to the customer."""
    dest = whatsapp_digits(to or software_number())
    source = whatsapp_digits(software_number())
    result = {
        "from": f"+{source}" if source else software_number(),
        "to": f"+{dest}" if dest else "",
        "provider": None,
        "ok": False,
        "error": "",
    }
    if not dest:
        result["error"] = "شماره مشتری خالی است."
        return result
    if not (text or "").strip():
        result["error"] = "متن پیام خالی است."
        return result

    ultramsg_id = _cfg("ULTRAMSG_INSTANCE", "ultramsg_instance")
    ultramsg_token = _cfg("ULTRAMSG_TOKEN", "ultramsg_token")
    if ultramsg_id and ultramsg_token:
        ok, body = _post_form(
            f"https://api.ultramsg.com/{ultramsg_id}/messages/chat",
            {"token": ultramsg_token, "to": f"+{dest}", "body": text},
        )
        result["provider"] = "ultramsg"
        result["ok"] = ok
        result["error"] = "" if ok else (body or "ارسال اولترا ناموفق بود.")
        return result

    green_id = _cfg("GREEN_API_INSTANCE", "green_api_instance")
    green_token = _cfg("GREEN_API_TOKEN", "green_api_token")
    if green_id and green_token:
        ok, body = _post_json(
            f"https://api.green-api.com/waInstance{green_id}/sendMessage/{green_token}",
            {"chatId": f"{dest}@c.us", "message": text},
        )
        result["provider"] = "green-api"
        result["ok"] = ok
        result["error"] = "" if ok else (body or "ارسال گرین ناموفق بود.")
        return result

    cloud_token = _cfg("WHATSAPP_TOKEN", "cloud_token")
    phone_id = _cfg("WHATSAPP_PHONE_NUMBER_ID", "cloud_phone_id")
    if cloud_token and phone_id:
        ok, body = _post_json(
            f"https://graph.facebook.com/v21.0/{phone_id}/messages",
            {
                "messaging_product": "whatsapp",
                "to": dest,
                "type": "text",
                "text": {"preview_url": True, "body": text},
            },
            headers={"Authorization": f"Bearer {cloud_token}"},
        )
        result["provider"] = "cloud"
        result["ok"] = ok
        result["error"] = "" if ok else (body or "ارسال کلاد ناموفق بود.")
        return result

    webhook = _cfg("WHATSAPP_API_URL", "api_url")
    if webhook:
        ok, body = _post_json(
            webhook,
            {"from": result["from"], "to": result["to"], "text": text},
        )
        result["provider"] = "webhook"
        result["ok"] = ok
        result["error"] = "" if ok else (body or "ارسال وب‌هوک ناموفق بود.")
        return result

    if _can_use_whatsapp_web():
        if os.environ.get("WHATSAPP_WEB_INLINE") == "1":
            return send_via_whatsapp_web(dest, text)
        return enqueue_whatsapp_web(dest, text, token=token, origin=origin, db_path=db_path)

    result["error"] = (
        "واتساپ وب روی این رایانه در دسترس نیست. روی ویندوز، https://web.whatsapp.com را باز بگذارید."
    )
    return result
