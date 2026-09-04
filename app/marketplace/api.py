"""HTTP API for buyer portal, auctions, and center office."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from . import service as svc

router = APIRouter()


def db(request: Request) -> Path | None:
    return getattr(request.app.state, "marketplace_db", None)


def bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    kind, _, token = authorization.partition(" ")
    if kind.lower() == "bearer" and token:
        return token.strip()
    return authorization.strip() or None


def current_user(request: Request, authorization: str | None = None) -> dict[str, Any]:
    token = bearer(authorization) or request.cookies.get("session")
    user = svc.session_user(token, db(request))
    if user is None:
        raise HTTPException(status_code=401, detail="وارد نشده‌اید.")
    return user


def staff_user(request: Request, authorization: str | None = None) -> dict[str, Any]:
    user = current_user(request, authorization)
    try:
        svc.require_staff(user)
    except svc.MarketplaceError as extra:
        raise wrap(extra) from extra
    return user


class RegisterBody(BaseModel):
    email: str
    password: str
    full_name: str = ""
    contact_person: str = ""
    phone: str = ""
    national_id: str = ""
    business_name: str = ""


class LoginBody(BaseModel):
    email: str
    password: str


class ResetBody(BaseModel):
    email: str = ""


class ResetConfirmBody(BaseModel):
    token: str
    password: str


class BidBody(BaseModel):
    amount: int = Field(..., gt=0)


class AutoBidBody(BaseModel):
    max_bid: int = Field(..., gt=0)


class PublishBody(BaseModel):
    duration_seconds: int = 60
    increment: int = 10_000
    participant_policy: str = "ALL_VERIFIED_BUYERS"


class AppointmentBody(BaseModel):
    date: str
    time: str
    customer_name: str = ""
    customer_phone: str = ""
    source: str = ""
    notes: str = ""
    brand: str = ""
    model: str = ""
    year: int | None = None
    starting_price: int | None = None
    ready_for_auction: bool = False
    publish: bool = False
    booking_appointment_id: int | None = None


class InspectionBody(BaseModel):
    summary: str = ""
    notes: str = ""
    report: dict[str, Any] | None = None
    finalize: bool = True


class VehicleBody(BaseModel):
    brand: str | None = None
    model: str | None = None
    year: int | None = None
    mileage: int | None = None
    transmission: str | None = None
    color: str | None = None
    body_type: str | None = None
    body_condition: str | None = None
    paint_status: str | None = None
    cabin_condition: str | None = None
    technical_condition: str | None = None
    fuel_type: str | None = None
    engine: str | None = None
    document_type: str | None = None
    insurance_months: int | None = None
    strengths: list[str] | str | None = None
    inspection_summary: str | None = None
    photos: list[str] | None = None
    starting_price: int | None = None
    reserve_price: int | None = None
    customer_name: str | None = None
    customer_phone: str | None = None
    customer_address: str | None = None
    vin: str | None = None
    plate: str | None = None


class BuyerStatusBody(BaseModel):
    status: str | None = None
    verification_status: str | None = None


def wrap(exc: svc.MarketplaceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post("/auth/register")
def register(body: RegisterBody, request: Request) -> dict[str, Any]:
    try:
        name = body.full_name or body.contact_person
        name, phone, national_id = svc.normalize_buyer_identity(name, body.phone, body.national_id, required=True)
        buyer = svc.register_buyer(
            body.email,
            body.password,
            body.business_name,
            name,
            phone,
            national_id,
            require_identity=True,
            db_path=db(request),
        )
    except svc.MarketplaceError as extra:
        raise wrap(extra) from extra
    return {"ok": True, "buyer": buyer}


@router.post("/auth/login")
def login(body: LoginBody, request: Request) -> dict[str, Any]:
    try:
        return svc.login(body.email, body.password, db(request))
    except svc.MarketplaceError as extra:
        raise wrap(extra) from extra


@router.post("/auth/logout")
def logout(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    token = bearer(authorization) or request.cookies.get("session")
    if token:
        svc.logout(token, db(request))
    return {"ok": True}


@router.post("/auth/forgot-password")
def forgot(body: ResetBody, request: Request) -> dict[str, Any]:
    return svc.forgot_password(body.email, db(request))


@router.post("/auth/reset-password")
def reset(body: ResetConfirmBody, request: Request) -> dict[str, Any]:
    try:
        svc.reset_password(body.token, body.password, db(request))
    except svc.MarketplaceError as extra:
        raise wrap(extra) from extra
    return {"ok": True}


@router.get("/buyers/me")
def me(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(request, authorization)
    buyer = svc.buyer_by_user(user["id"], db(request)) if user["role"] == "BUYER" else None
    return {"user": svc.public_user(user, db(request)), "buyer": buyer}


@router.put("/buyers/me")
def update_me(body: dict[str, Any], request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(request, authorization)
    try:
        buyer = svc.require_buyer(user, db(request))
        return svc.update_buyer_profile(buyer["id"], body, db(request))
    except svc.MarketplaceError as extra:
        raise wrap(extra) from extra


@router.get("/buyers/me/preferences")
def my_prefs(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(request, authorization)
    buyer = svc.require_buyer(user, db(request))
    return svc.get_preferences(buyer["id"], db(request))


@router.put("/buyers/me/preferences")
def put_prefs(body: dict[str, Any], request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(request, authorization)
    buyer = svc.require_buyer(user, db(request))
    return svc.update_preferences(buyer["id"], body, db(request))


@router.get("/buyers/me/bids")
def my_bids(request: Request, authorization: str | None = Header(default=None)) -> list[dict[str, Any]]:
    user = current_user(request, authorization)
    buyer = svc.require_buyer(user, db(request))
    return svc.buyer_bid_history(buyer["id"], db(request))


@router.get("/buyers/me/auctions")
def my_auctions(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(request, authorization)
    buyer = svc.require_buyer(user, db(request))
    return svc.buyer_auction_history(buyer["id"], db(request))


@router.get("/buyers/me/notifications")
def my_notes(request: Request, authorization: str | None = Header(default=None)) -> list[dict[str, Any]]:
    user = current_user(request, authorization)
    return svc.list_notifications(user["id"], db(request))


@router.get("/buyer/appointments")
def buyer_appts(request: Request, authorization: str | None = Header(default=None)) -> list[dict[str, Any]]:
    current_user(request, authorization)
    return svc.buyer_appointments(db(request))


@router.get("/live")
def live(request: Request, authorization: str | None = Header(default=None)) -> dict[str, int]:
    current_user(request, authorization)
    return svc.live_state(db(request))


@router.get("/auctions")
def auctions(request: Request, authorization: str | None = Header(default=None)) -> list[dict[str, Any]]:
    user = current_user(request, authorization)
    buyer = svc.require_buyer(user, db(request))
    return svc.buyer_visible_auctions(buyer, db(request))


@router.get("/auctions/{auction_id}")
def auction_detail(auction_id: int, request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(request, authorization)
    try:
        buyer = svc.require_buyer(user, db(request))
        return svc.buyer_auction_detail(auction_id, buyer, db(request))
    except svc.MarketplaceError as extra:
        raise wrap(extra) from extra


@router.post("/auctions/{auction_id}/bids")
def bid(
    auction_id: int,
    body: BidBody,
    request: Request,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    user = current_user(request, authorization)
    try:
        buyer = svc.require_buyer(user, db(request))
        result = svc.place_manual_bid(auction_id, buyer, body.amount, request_id=idempotency_key, db_path=db(request))
        result["bid"] = {key: result["bid"][key] for key in result["bid"] if key != "request_id"}
        return result
    except svc.MarketplaceError as extra:
        raise wrap(extra) from extra


@router.post("/auctions/{auction_id}/auto-bid")
def auto_bid(
    auction_id: int,
    body: AutoBidBody,
    request: Request,
    authorization: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    user = current_user(request, authorization)
    try:
        buyer = svc.require_buyer(user, db(request))
        return svc.set_auto_bid(auction_id, buyer, body.max_bid, request_id=idempotency_key, db_path=db(request))
    except svc.MarketplaceError as extra:
        raise wrap(extra) from extra


@router.delete("/auctions/{auction_id}/auto-bid")
def delete_auto(auction_id: int, request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(request, authorization)
    buyer = svc.require_buyer(user, db(request))
    return svc.clear_auto_bid(auction_id, buyer, db(request))


@router.get("/auctions/{auction_id}/bids")
def auction_bids(auction_id: int, request: Request, authorization: str | None = Header(default=None)) -> list[dict[str, Any]]:
    user = current_user(request, authorization)
    path = db(request)
    if user["role"] in {"OFFICE", "ADMIN"}:
        return svc.list_bids(auction_id, office=True, db_path=path)
    buyer = svc.require_buyer(user, path)
    auction = svc.get_auction(auction_id, path)
    if not svc.buyer_may_see_auction(buyer, auction, path):
        raise HTTPException(status_code=404, detail="مزایده پیدا نشد.")
    return svc.list_bids(auction_id, viewer_buyer_id=buyer["id"], db_path=path)


@router.get("/office/dashboard")
def office_dash(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    staff_user(request, authorization)
    return svc.office_dashboard(db(request))


@router.post("/office/appointments")
def office_add_appt(body: AppointmentBody, request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = staff_user(request, authorization)
    return svc.create_appointment(
        body.date,
        body.time,
        body.customer_name,
        body.customer_phone,
        db(request),
        source=body.source,
        notes=body.notes,
        brand=body.brand,
        model=body.model,
        year=body.year,
        starting_price=body.starting_price or 0,
        ready_for_auction=body.ready_for_auction,
        publish=body.publish,
        booking_appointment_id=body.booking_appointment_id,
    )


@router.put("/office/appointments/{appointment_id}")
def office_edit_appt(appointment_id: int, body: AppointmentBody, request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    staff_user(request, authorization)
    return svc.update_appointment(
        appointment_id,
        {
            "date": body.date,
            "time": body.time,
            "customer_name": body.customer_name,
            "customer_phone": body.customer_phone,
            "notes": body.notes,
            "source": body.source or None,
        },
        db(request),
    )


@router.delete("/office/appointments/{appointment_id}")
def office_delete_appt(appointment_id: int, request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    staff_user(request, authorization)
    try:
        return svc.delete_appointment(appointment_id, db(request))
    except svc.MarketplaceError as extra:
        raise wrap(extra) from extra


@router.post("/office/appointments/import-booking/{booking_id}")
def office_import_booking(booking_id: int, request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    staff_user(request, authorization)
    try:
        return svc.import_booking_appointment(booking_id, db(request))
    except svc.MarketplaceError as extra:
        raise wrap(extra) from extra


@router.post("/office/appointments/{appointment_id}/status")
def office_appt_status(appointment_id: int, body: dict[str, Any], request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = staff_user(request, authorization)
    return svc.set_appointment_status(appointment_id, str(body.get("status") or ""), db(request))


@router.get("/office/vehicles/{vehicle_id}")
def office_vehicle(vehicle_id: int, request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = staff_user(request, authorization)
    vehicle = svc.get_vehicle(vehicle_id, db(request))
    auction = svc.auction_for_vehicle(vehicle_id, db(request))
    return {"vehicle": vehicle, "auction": auction, "winner": svc.get_winner(auction["id"], db(request)) if auction else None}


@router.put("/office/vehicles/{vehicle_id}")
def office_update_vehicle(vehicle_id: int, body: VehicleBody, request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = staff_user(request, authorization)
    return svc.update_vehicle(vehicle_id, body.model_dump(exclude_none=True), db(request))


@router.get("/inspection-catalog")
def catalog(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    current_user(request, authorization)
    return svc.inspection_catalog()


@router.post("/office/vehicles/{vehicle_id}/inspect")
def office_inspect(vehicle_id: int, request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = staff_user(request, authorization)
    return svc.start_inspection(vehicle_id, db(request))


@router.get("/office/vehicles/{vehicle_id}/inspection")
def office_get_inspection(vehicle_id: int, request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    staff_user(request, authorization)
    inspection = svc.get_inspection(vehicle_id, db(request))
    if inspection is None:
        raise HTTPException(status_code=404, detail="کارشناسی ثبت نشده است.")
    return inspection


@router.put("/office/vehicles/{vehicle_id}/inspection")
def office_save_inspection(vehicle_id: int, body: InspectionBody, request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    staff_user(request, authorization)
    return svc.save_inspection(
        vehicle_id,
        report=body.report,
        summary=body.summary,
        notes=body.notes,
        finalize=False,
        db_path=db(request),
    )


@router.post("/office/vehicles/{vehicle_id}/finalize-inspection")
def office_finalize(vehicle_id: int, body: InspectionBody, request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = staff_user(request, authorization)
    if body.report is not None:
        return svc.save_inspection(
            vehicle_id,
            report=body.report,
            summary=body.summary,
            notes=body.notes,
            finalize=True,
            db_path=db(request),
        )
    return svc.finalize_inspection(vehicle_id, body.summary, db_path=db(request))


@router.post("/office/vehicles/{vehicle_id}/approve")
def office_approve(vehicle_id: int, request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = staff_user(request, authorization)
    try:
        return svc.approve_vehicle(vehicle_id, db(request))
    except svc.MarketplaceError as extra:
        raise wrap(extra) from extra


@router.post("/office/vehicles/{vehicle_id}/publish")
def office_publish(vehicle_id: int, body: PublishBody | None = None, request: Request = None, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = staff_user(request, authorization)
    payload = body or PublishBody()
    try:
        return svc.publish_vehicle(
            vehicle_id,
            duration_seconds=payload.duration_seconds,
            increment=payload.increment,
            participant_policy=payload.participant_policy,
            db_path=db(request),
        )
    except svc.MarketplaceError as extra:
        raise wrap(extra) from extra


@router.post("/office/auctions/{auction_id}/start")
def office_start(auction_id: int, request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = staff_user(request, authorization)
    return svc.set_auction_status(auction_id, "ACTIVE", db(request))


@router.post("/office/auctions/{auction_id}/pause")
def office_pause(auction_id: int, request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = staff_user(request, authorization)
    return svc.set_auction_status(auction_id, "SCHEDULED", db(request))


@router.post("/office/auctions/{auction_id}/cancel")
def office_cancel(auction_id: int, request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = staff_user(request, authorization)
    return svc.cancel_auction(auction_id, db(request))


@router.get("/office/auctions/{auction_id}/bids")
def office_bids(auction_id: int, request: Request, authorization: str | None = Header(default=None)) -> list[dict[str, Any]]:
    user = staff_user(request, authorization)
    return svc.list_bids(auction_id, office=True, db_path=db(request))


@router.get("/office/auctions/{auction_id}/participants")
def office_parts(auction_id: int, request: Request, authorization: str | None = Header(default=None)) -> list[dict[str, Any]]:
    user = staff_user(request, authorization)
    return svc.list_participants(auction_id, db(request))


@router.get("/office/auctions/{auction_id}/winner")
def office_winner(auction_id: int, request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = staff_user(request, authorization)
    winner = svc.get_winner(auction_id, db(request))
    if winner is None:
        raise HTTPException(status_code=404, detail="برنده‌ای ثبت نشده است.")
    return winner


@router.post("/office/auctions/{auction_id}/accept-winner")
def office_accept(auction_id: int, request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = staff_user(request, authorization)
    try:
        return svc.accept_winner(auction_id, db(request))
    except svc.MarketplaceError as extra:
        raise wrap(extra) from extra


@router.post("/office/auctions/{auction_id}/reject-winner")
def office_reject(auction_id: int, request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = staff_user(request, authorization)
    try:
        return svc.reject_winner(auction_id, db(request))
    except svc.MarketplaceError as extra:
        raise wrap(extra) from extra


@router.post("/office/buyers/{buyer_id}/status")
def office_buyer_status(buyer_id: int, body: BuyerStatusBody, request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = staff_user(request, authorization)
    return svc.set_buyer_status(buyer_id, body.status, body.verification_status, db(request))


@router.put("/office/buyers/{buyer_id}")
def office_edit_buyer(buyer_id: int, body: dict[str, Any], request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    staff_user(request, authorization)
    if svc.get_buyer_profile(buyer_id, db(request)) is None:
        raise HTTPException(status_code=404, detail="خریدار پیدا نشد.")
    try:
        return svc.update_buyer_profile(buyer_id, body, db(request))
    except svc.MarketplaceError as extra:
        raise wrap(extra) from extra


@router.get("/buyers/{buyer_id}")
def other_buyer(buyer_id: int, request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    user = current_user(request, authorization)
    if user["role"] not in {"OFFICE", "ADMIN"}:
        raise HTTPException(status_code=403, detail="مشاهده پروفایل دیگران مجاز نیست.")
    profile = svc.get_buyer_profile(buyer_id, db(request))
    if profile is None:
        raise HTTPException(status_code=404, detail="خریدار پیدا نشد.")
    return profile
