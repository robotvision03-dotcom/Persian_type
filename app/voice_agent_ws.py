"""Browser <-> OpenAI Realtime (GA) websocket proxy for the voice agent."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from . import voice_agent
from .dialogue import DialogueManager

logger = logging.getLogger(__name__)


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    if ws.client_state == WebSocketState.CONNECTED:
        await ws.send_json(payload)


async def _send_bytes(ws: WebSocket, data: bytes) -> None:
    if ws.client_state == WebSocketState.CONNECTED:
        await ws.send_bytes(data)


async def run_voice_agent_proxy(
    browser: WebSocket,
    *,
    dialogue: DialogueManager,
    origin: str,
    deliver_invite: Callable[..., Any],
) -> None:
    """Bridge browser mic/speaker audio to OpenAI Realtime GA and booking tools."""
    await browser.accept()
    if not voice_agent.is_configured():
        await _send_json(
            browser,
            {
                "type": "error",
                "message": "کلید OPENAI_API_KEY روی سرور تنظیم نشده است.",
            },
        )
        await browser.close()
        return

    try:
        import websockets
    except ImportError as exc:  # pragma: no cover
        await _send_json(browser, {"type": "error", "message": f"websockets نصب نیست: {exc}"})
        await browser.close()
        return

    session_id = ""
    started = False
    openai_ws = None

    try:
        openai_ws = await websockets.connect(
            voice_agent.realtime_ws_url(),
            additional_headers=voice_agent.openai_headers(),
            max_size=8 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=20,
            open_timeout=20,
        )
        await openai_ws.send(json.dumps(voice_agent.session_update_event()))
        await _send_json(
            browser,
            {
                "type": "status",
                "message": "عامل صوتی ابری متصل شد",
                "provider": "openai_realtime",
                "model": voice_agent.DEFAULT_MODEL,
            },
        )

        async def from_browser() -> None:
            nonlocal session_id, started
            while True:
                message = await browser.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                data = message.get("bytes")
                text = message.get("text")
                if text:
                    try:
                        payload = json.loads(text)
                    except json.JSONDecodeError:
                        payload = {"type": text}
                    kind = str(payload.get("type") or "").lower()
                    session_id = str(payload.get("session_id") or session_id)
                    if kind in {"start", "hello"}:
                        if not session_id:
                            session_id = "voice-" + str(id(browser))
                        if not started:
                            turn = await asyncio.to_thread(dialogue.start, session_id)
                            started = True
                            greeting = turn.get("reply") or "سلام وقت بخیر. لطفا اسم خودرو را بگویید."
                            await _send_json(
                                browser,
                                {
                                    "type": "assistant_text",
                                    "text": greeting,
                                    "turn": turn,
                                },
                            )
                            await openai_ws.send(
                                json.dumps(
                                    voice_agent.response_create_event(
                                        "با همان متن فارسی زیر به مشتری سلام کن و دقیقاً همین را بگو، "
                                        "بدون افزودن جمله اضافه:\n"
                                        f"{greeting}"
                                    )
                                )
                            )
                        continue
                    if kind in {"hangup", "stop", "end"}:
                        break
                    if kind == "text":
                        user_text = str(payload.get("text") or "").strip()
                        if user_text and session_id:
                            await openai_ws.send(
                                json.dumps(
                                    {
                                        "type": "conversation.item.create",
                                        "item": {
                                            "type": "message",
                                            "role": "user",
                                            "content": [
                                                {"type": "input_text", "text": user_text}
                                            ],
                                        },
                                    }
                                )
                            )
                            await openai_ws.send(json.dumps(voice_agent.response_create_event()))
                        continue
                    continue
                if not data:
                    continue
                await openai_ws.send(
                    json.dumps(
                        {
                            "type": "input_audio_buffer.append",
                            "audio": voice_agent.pcm16_b64(data),
                        }
                    )
                )

        async def from_openai() -> None:
            nonlocal session_id
            async for raw in openai_ws:
                event = json.loads(raw)
                etype = event.get("type") or ""

                if etype == "error":
                    err = event.get("error") or {}
                    detail = err.get("message") or str(event)
                    code = err.get("code") or ""
                    await _send_json(
                        browser,
                        {
                            "type": "error",
                            "message": voice_agent.humanize_openai_error(f"{code} {detail}"),
                        },
                    )
                    continue

                if etype == "input_audio_buffer.speech_started":
                    await _send_json(browser, {"type": "status", "message": "در حال شنیدن..."})
                    continue

                if etype == "input_audio_buffer.speech_stopped":
                    await _send_json(browser, {"type": "status", "message": "در حال فکر کردن..."})
                    continue

                if etype == "conversation.item.input_audio_transcription.completed":
                    transcript = (event.get("transcript") or "").strip()
                    if transcript:
                        await _send_json(
                            browser,
                            {"type": "user_transcript", "text": transcript},
                        )
                    continue

                if etype in {
                    "response.audio_transcript.delta",
                    "response.output_audio_transcript.delta",
                }:
                    delta = event.get("delta") or ""
                    if delta:
                        await _send_json(
                            browser,
                            {"type": "assistant_partial", "text": delta},
                        )
                    continue

                if etype in {
                    "response.audio_transcript.done",
                    "response.output_audio_transcript.done",
                }:
                    transcript = (event.get("transcript") or "").strip()
                    if transcript:
                        await _send_json(
                            browser,
                            {"type": "assistant_text", "text": transcript},
                        )
                    continue

                if etype in {"response.audio.delta", "response.output_audio.delta"}:
                    b64 = event.get("delta") or ""
                    if b64:
                        await _send_bytes(browser, voice_agent.b64_to_bytes(b64))
                    continue

                if etype in {
                    "response.function_call_arguments.done",
                    "response.output_item.done",
                }:
                    # GA may wrap function calls differently; support both shapes.
                    name = event.get("name") or ""
                    call_id = event.get("call_id") or ""
                    args = event.get("arguments") or "{}"
                    item = event.get("item") or {}
                    if item.get("type") == "function_call":
                        name = item.get("name") or name
                        call_id = item.get("call_id") or call_id
                        args = item.get("arguments") or args
                    if not name:
                        continue
                    result = await asyncio.to_thread(
                        voice_agent.run_tool,
                        name,
                        args,
                        session_id=session_id or "voice-unknown",
                        dialogue=dialogue,
                        origin=origin,
                        deliver_invite=deliver_invite,
                    )
                    await _send_json(
                        browser,
                        {
                            "type": "tool_result",
                            "name": name,
                            "result": result,
                            "turn": result if name == "process_customer_utterance" else None,
                        },
                    )
                    await openai_ws.send(
                        json.dumps(
                            {
                                "type": "conversation.item.create",
                                "item": {
                                    "type": "function_call_output",
                                    "call_id": call_id,
                                    "output": json.dumps(result, ensure_ascii=False),
                                },
                            }
                        )
                    )
                    speak = ""
                    if isinstance(result, dict):
                        speak = str(result.get("speak") or result.get("reply") or "")
                    if speak:
                        await openai_ws.send(
                            json.dumps(
                                voice_agent.response_create_event(
                                    "فقط همین متن فارسی را برای مشتری بلند بگو و چیزی اضافه نکن:\n"
                                    f"{speak}"
                                )
                            )
                        )
                    else:
                        await openai_ws.send(json.dumps(voice_agent.response_create_event()))
                    if isinstance(result, dict) and result.get("end_call"):
                        await _send_json(
                            browser,
                            {
                                "type": "end_call",
                                "message": "نوبت آماده شد؛ لینک تقویم ارسال شد.",
                                "turn": result,
                            },
                        )
                    continue

                if etype in {"session.updated", "session.created"}:
                    await _send_json(browser, {"type": "status", "message": "آماده گفتگو"})
                    continue

        browser_task = asyncio.create_task(from_browser())
        openai_task = asyncio.create_task(from_openai())
        done, pending = await asyncio.wait(
            {browser_task, openai_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, (WebSocketDisconnect, asyncio.CancelledError)):
                logger.exception("voice agent proxy failed: %s", exc)
                await _send_json(
                    browser,
                    {"type": "error", "message": voice_agent.humanize_openai_error(str(exc))},
                )
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.exception("voice agent connection error")
        detail = voice_agent.humanize_openai_error(str(exc))
        try:
            await _send_json(browser, {"type": "error", "message": detail})
        except Exception:
            pass
    finally:
        if openai_ws is not None:
            try:
                await openai_ws.close()
            except Exception:
                pass
        if session_id:
            try:
                await asyncio.to_thread(dialogue.hangup, session_id)
            except Exception:
                pass
        try:
            if browser.client_state == WebSocketState.CONNECTED:
                await browser.close()
        except Exception:
            pass
