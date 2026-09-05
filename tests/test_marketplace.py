import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app.marketplace import service as svc
from app.marketplace.matching import match_score
from app.marketplace.privacy import safe_appointment
from app.server import app, reset_state

try:
    from fastapi.testclient import TestClient
except Exception:
    TestClient = None


def _db():
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / "market.sqlite"
    svc.bootstrap(path)
    return tmp, path


def _buyer(path, email, password="Secret123"):
    buyer = svc.register_buyer(email, password, business_name=email.split("@")[0], db_path=path)
    svc.activate_buyer(buyer["id"], db_path=path)
    session = svc.login(email, password, db_path=path)
    return session, svc.buyer_by_user(session["user"]["id"], path)


def _pipeline(path, start=1_300_000_000, reserve=None, duration=3600, now=None, increment=5_000_000):
    when = now or datetime(2026, 9, 5, 9, 0, 0)
    appt = svc.create_appointment("2026-09-05", "10:30", "علی رضایی", "09120000000", db_path=path, now=when)
    vehicle = next(item for item in svc.list_vehicles(path) if item["appointment_id"] == appt["id"])
    svc.start_inspection(vehicle["id"], db_path=path, now=when)
    svc.finalize_inspection(vehicle["id"], "سالم", db_path=path, now=when)
    svc.update_vehicle(
        vehicle["id"],
        {
            "brand": "پژو",
            "model": "207",
            "year": 1401,
            "mileage": 82000,
            "transmission": "اتومات",
            "color": "سفید",
            "starting_price": start,
            "reserve_price": reserve,
            "vin": "SECRETVIN",
            "plate": "12ب345",
        },
        db_path=path,
        now=when,
    )
    svc.approve_vehicle(vehicle["id"], db_path=path, now=when)
    auction = svc.publish_vehicle(vehicle["id"], duration_seconds=duration, increment=increment, db_path=path, now=when)
    return appt, svc.get_vehicle(vehicle["id"], path), auction


class AuthTests(unittest.TestCase):
    def test_register_login_and_invalid(self):
        tmp, path = _db()
        with tmp:
            buyer = svc.register_buyer(
                "a@ex.com",
                "Secret123",
                contact_person="علی رضایی",
                phone="09121234567",
                national_id="0012345678",
                require_identity=True,
                db_path=path,
            )
            self.assertEqual(buyer["status"], "PENDING")
            self.assertEqual(buyer["contact_person"], "علی رضایی")
            self.assertEqual(buyer["phone"], "09121234567")
            self.assertEqual(buyer["national_id"], "0012345678")
            self.assertEqual(buyer["verification_status"], "UNVERIFIED")
            session = svc.login("a@ex.com", "Secret123", db_path=path)
            self.assertTrue(session["token"])
            self.assertEqual(session["user"]["buyer"]["contact_person"], "علی رضایی")
            with self.assertRaises(svc.MarketplaceError):
                svc.login("a@ex.com", "wrong", db_path=path)
            svc.logout(session["token"], db_path=path)
            self.assertIsNone(svc.session_user(session["token"], db_path=path))

    def test_password_reset(self):
        tmp, path = _db()
        with tmp:
            svc.register_buyer("a@ex.com", "Secret123", db_path=path)
            forgot = svc.forgot_password("a@ex.com", db_path=path)
            svc.reset_password(forgot["reset_token"], "Newpass1", db_path=path)
            svc.login("a@ex.com", "Newpass1", db_path=path)
            with self.assertRaises(svc.MarketplaceError):
                svc.login("a@ex.com", "Secret123", db_path=path)

    def test_profile_update_and_suspend(self):
        tmp, path = _db()
        with tmp:
            session, buyer = _buyer(path, "a@ex.com")
            updated = svc.update_buyer_profile(
                buyer["id"],
                {"city": "تهران", "business_name": "نمایشگاه الف", "full_name": "مریم احمدی", "phone": "09123334455"},
                db_path=path,
            )
            self.assertEqual(updated["city"], "تهران")
            self.assertEqual(updated["contact_person"], "مریم احمدی")
            self.assertEqual(updated["phone"], "09123334455")
            svc.set_buyer_status(buyer["id"], status="SUSPENDED", db_path=path)
            frozen = svc.get_buyer_profile(buyer["id"], path)
            self.assertEqual(frozen["status"], "SUSPENDED")
            self.assertFalse(svc.can_bid(frozen))


class AppointmentAdminTests(unittest.TestCase):
    def test_edit_cancel_and_delete_appointment(self):
        tmp, path = _db()
        with tmp:
            appt = svc.create_appointment("2026-09-05", "10:30", "علی رضایی", "09120000000", db_path=path)
            updated = svc.update_appointment(appt["id"], {"date": "2026-09-06", "time": "11:15", "customer_name": "مریم"}, db_path=path)
            self.assertEqual(updated["date"], "2026-09-06")
            self.assertEqual(updated["time"], "11:15")
            self.assertEqual(updated["customer_name"], "مریم")
            buyers = svc.buyer_appointments(path)
            self.assertTrue(any(row["time"] == "11:15" for row in buyers))
            cancelled = svc.set_appointment_status(appt["id"], "CANCELLED", db_path=path)
            self.assertEqual(cancelled["status"], "CANCELLED")
            self.assertFalse(any(row.get("time") == "11:15" and row.get("status") != "CANCELLED" for row in svc.buyer_appointments(path)))
            svc.delete_appointment(appt["id"], db_path=path)
            with self.assertRaises(svc.MarketplaceError):
                svc.get_appointment(appt["id"], path)

    def test_off_hours_walk_in_can_publish(self):
        tmp, path = _db()
        with tmp:
            when = datetime(2026, 9, 4, 21, 30, 0)
            created = svc.create_appointment(
                "2026-09-04",
                "21:30",
                "ورود فوری",
                "09120000001",
                db_path=path,
                now=when,
                source="WALK_IN",
                brand="پژو",
                model="207",
                starting_price=2_000_000,
                publish=True,
            )
            self.assertIn("auction", created)
            appt = created["appointment"]
            self.assertTrue(appt["off_hours"])
            self.assertEqual(appt["source"], "WALK_IN")
            self.assertEqual(created["vehicle"]["status"], "BIDDING_ACTIVE")
            _, buyer = _buyer(path, "walk@ex.com")
            visible = svc.buyer_visible_auctions(buyer, path, now=when)
            self.assertEqual(len(visible), 1)
            self.assertEqual(visible[0]["brand"], "پژو")


class AppointmentPrivacyTests(unittest.TestCase):
    def test_buyer_sees_time_only(self):
        tmp, path = _db()
        with tmp:
            appt = svc.create_appointment("2026-09-05", "10:30", "علی رضایی", "09120000000", db_path=path)
            rows = svc.buyer_appointments(path)
            self.assertTrue(any(row["time"] == "10:30" for row in rows))
            for row in rows:
                self.assertNotIn("customer_name", row)
                self.assertNotIn("customer_phone", row)
                self.assertNotIn("علی", str(row))
                self.assertEqual(set(row), {"date", "time", "status"})
            office = svc.get_appointment(appt["id"], path)
            self.assertEqual(office["customer_name"], "علی رضایی")
            vehicle = next(item for item in svc.list_vehicles(path) if item["appointment_id"] == appt["id"])
            self.assertEqual(vehicle["status"], "APPOINTMENT_SCHEDULED")
            session, buyer = _buyer(path, "b@ex.com")
            self.assertEqual(svc.buyer_visible_auctions(buyer, path), [])

    def test_safe_appointment_serializer(self):
        safe = safe_appointment({"date": "2026-09-05", "time": "09:00", "customer_name": "علی", "vin": "X"})
        self.assertEqual(safe, {"date": "2026-09-05", "time": "09:00", "status": "SCHEDULED"})


class AuctionVisibilityTests(unittest.TestCase):
    def test_only_published_active_is_visible(self):
        tmp, path = _db()
        with tmp:
            when = datetime(2026, 9, 5, 9, 0, 0)
            appt = svc.create_appointment("2026-09-05", "10:30", "علی", "0912", db_path=path, now=when)
            vehicle = next(item for item in svc.list_vehicles(path) if item["appointment_id"] == appt["id"])
            session, buyer = _buyer(path, "b@ex.com")
            self.assertEqual(svc.buyer_visible_auctions(buyer, path, now=when), [])
            svc.start_inspection(vehicle["id"], db_path=path, now=when)
            svc.finalize_inspection(vehicle["id"], "ok", db_path=path, now=when)
            self.assertEqual(svc.buyer_visible_auctions(buyer, path, now=when), [])
            svc.update_vehicle(vehicle["id"], {"brand": "پژو", "model": "207", "starting_price": 1000}, db_path=path)
            svc.approve_vehicle(vehicle["id"], db_path=path, now=when)
            self.assertEqual(svc.get_vehicle(vehicle["id"], path)["status"], "READY_FOR_BIDDING")
            self.assertEqual(svc.buyer_visible_auctions(buyer, path, now=when), [])
            auction = svc.publish_vehicle(vehicle["id"], db_path=path, now=when)
            visible = svc.buyer_visible_auctions(buyer, path, now=when)
            self.assertEqual(len(visible), 1)
            self.assertNotIn("vin", visible[0])
            self.assertNotIn("customer_name", visible[0])
            self.assertEqual(visible[0]["auction"]["id"], auction["id"])


class BiddingTests(unittest.TestCase):
    def test_manual_bids_and_rejection(self):
        tmp, path = _db()
        with tmp:
            when = datetime(2026, 9, 5, 9, 0, 0)
            _appt, _vehicle, auction = _pipeline(path, now=when)
            _, a = _buyer(path, "a@ex.com")
            _, b = _buyer(path, "b@ex.com")
            first = svc.place_manual_bid(auction["id"], a, 1_300_000_000, db_path=path, now=when)
            self.assertEqual(first["auction"]["current_winner_id"], a["id"])
            with self.assertRaises(svc.MarketplaceError):
                svc.place_manual_bid(auction["id"], b, 1_301_000_000, db_path=path, now=when)
            second = svc.place_manual_bid(auction["id"], b, 1_306_500_000, db_path=path, now=when)
            self.assertEqual(second["auction"]["current_winner_id"], b["id"])
            self.assertEqual(second["auction"]["current_price"], 1_306_500_000)

    def test_auto_bid_two_buyers(self):
        tmp, path = _db()
        with tmp:
            when = datetime(2026, 9, 5, 9, 0, 0)
            _appt, _vehicle, auction = _pipeline(path, now=when)
            _, a = _buyer(path, "a@ex.com")
            _, b = _buyer(path, "b@ex.com")
            svc.set_auto_bid(auction["id"], a, 1_400_000_000, db_path=path, now=when)
            result = svc.set_auto_bid(auction["id"], b, 1_350_000_000, db_path=path, now=when)
            self.assertEqual(result["auction"]["current_winner_id"], a["id"])
            self.assertEqual(result["auction"]["current_price"], 1_356_500_000)
            self.assertNotIn("max_bid", result["auto_bid"])
            other = svc.my_auto_bid(auction["id"], a["id"], path)
            self.assertEqual(other["max_bid"], 1_400_000_000)

    def test_higher_max_wins(self):
        tmp, path = _db()
        with tmp:
            when = datetime(2026, 9, 5, 9, 0, 0)
            _appt, _vehicle, auction = _pipeline(path, now=when)
            _, a = _buyer(path, "a@ex.com")
            _, b = _buyer(path, "b@ex.com")
            svc.set_auto_bid(auction["id"], a, 1_400_000_000, db_path=path, now=when)
            result = svc.set_auto_bid(auction["id"], b, 1_450_000_000, db_path=path, now=when)
            self.assertEqual(result["auction"]["current_winner_id"], b["id"])
            self.assertEqual(result["auction"]["current_price"], 1_406_500_000)

    def test_update_max_and_same_max(self):
        tmp, path = _db()
        with tmp:
            when = datetime(2026, 9, 5, 9, 0, 0)
            _appt, _vehicle, auction = _pipeline(path, now=when)
            _, a = _buyer(path, "a@ex.com")
            _, b = _buyer(path, "b@ex.com")
            svc.set_auto_bid(auction["id"], a, 1_400_000_000, db_path=path, now=when)
            svc.set_auto_bid(auction["id"], b, 1_400_000_000, db_path=path, now=when + timedelta(seconds=5))
            auction = svc.get_auction(auction["id"], path)
            self.assertEqual(auction["current_winner_id"], a["id"])
            self.assertEqual(auction["current_price"], 1_400_000_000)
            result = svc.set_auto_bid(auction["id"], b, 1_450_000_000, db_path=path, now=when)
            self.assertEqual(result["auction"]["current_winner_id"], b["id"])

    def test_reserve_and_expire(self):
        tmp, path = _db()
        with tmp:
            when = datetime(2026, 9, 5, 9, 0, 0)
            _appt, _vehicle, auction = _pipeline(path, start=1000, reserve=2000, duration=60, increment=100, now=when)
            _, a = _buyer(path, "a@ex.com")
            svc.place_manual_bid(auction["id"], a, 1500, db_path=path, now=when)
            closed = svc.close_if_expired(auction["id"], db_path=path, now=when + timedelta(minutes=10))
            self.assertEqual(closed["status"], "ENDED")
            winner = svc.get_winner(auction["id"], path)
            self.assertFalse(winner["reserve_met"])
            self.assertEqual(winner["status"], "PENDING_OFFICE_CONFIRMATION")
            with self.assertRaises(svc.MarketplaceError):
                svc.accept_winner(auction["id"], db_path=path, now=when + timedelta(minutes=10))

    def test_anti_sniping(self):
        tmp, path = _db()
        with tmp:
            when = datetime(2026, 9, 5, 9, 0, 0)
            _appt, _vehicle, auction = _pipeline(path, start=1000, duration=60, increment=100, now=when)
            _, a = _buyer(path, "a@ex.com")
            late = when + timedelta(seconds=50)
            result = svc.place_manual_bid(auction["id"], a, 1000, db_path=path, now=late)
            end = datetime.fromisoformat(result["auction"]["end_time"])
            self.assertGreater(end, when + timedelta(seconds=60))
            self.assertEqual(result["auction"]["extensions_used"], 1)

    def test_duplicate_request(self):
        tmp, path = _db()
        with tmp:
            when = datetime(2026, 9, 5, 9, 0, 0)
            _appt, _vehicle, auction = _pipeline(path, start=1000, increment=100, now=when)
            _, a = _buyer(path, "a@ex.com")
            first = svc.place_manual_bid(auction["id"], a, 1000, request_id="req-1", db_path=path, now=when)
            second = svc.place_manual_bid(auction["id"], a, 1000, request_id="req-1", db_path=path, now=when)
            self.assertTrue(second["duplicate"])
            self.assertEqual(first["bid"]["id"], second["bid"]["id"])
            history = svc.list_bids(auction["id"], office=True, db_path=path)
            manuals = [row for row in history if row["bid_type"] == "MANUAL"]
            self.assertEqual(len(manuals), 1)

    def test_inactive_rejects_bid(self):
        tmp, path = _db()
        with tmp:
            when = datetime(2026, 9, 5, 9, 0, 0)
            _appt, _vehicle, auction = _pipeline(path, start=1000, increment=100, now=when)
            _, a = _buyer(path, "a@ex.com")
            svc.set_auction_status(auction["id"], "CANCELLED", db_path=path, now=when)
            with self.assertRaises(svc.MarketplaceError):
                svc.place_manual_bid(auction["id"], a, 1000, db_path=path, now=when)

    def test_concurrent_bids(self):
        tmp, path = _db()
        with tmp:
            when = datetime(2026, 9, 5, 9, 0, 0)
            _appt, _vehicle, auction = _pipeline(path, start=1000, increment=100, now=when)
            _, a = _buyer(path, "a@ex.com")
            _, b = _buyer(path, "b@ex.com")
            errors = []

            def bid(buyer, amount):
                try:
                    svc.place_manual_bid(auction["id"], buyer, amount, db_path=path, now=when)
                except Exception as extra:
                    errors.append(extra)

            first = threading.Thread(target=bid, args=(a, 1100))
            second = threading.Thread(target=bid, args=(b, 1200))
            first.start()
            second.start()
            first.join()
            second.join()
            current = svc.get_auction(auction["id"], path)
            self.assertIn(current["current_price"], {1100, 1200})
            self.assertIsNotNone(current["current_winner_id"])
            self.assertLessEqual(len(errors), 1)


class SecurityTests(unittest.TestCase):
    def test_buyer_cannot_see_private_data(self):
        tmp, path = _db()
        with tmp:
            when = datetime(2026, 9, 5, 9, 0, 0)
            _appt, vehicle, auction = _pipeline(path, now=when)
            session_a, a = _buyer(path, "a@ex.com")
            session_b, b = _buyer(path, "b@ex.com")
            svc.set_auto_bid(auction["id"], a, 1_400_000_000, db_path=path, now=when)
            detail = svc.buyer_auction_detail(auction["id"], b, db_path=path, now=when)
            self.assertNotIn("vin", detail)
            self.assertNotIn("plate", detail)
            self.assertNotIn("customer_name", detail)
            self.assertNotIn("max_bid", str(detail.get("my_auto_bid")))
            for item in detail["bids"]:
                self.assertNotIn("buyer_id", item)
            other = svc.get_buyer_profile(a["id"], path)
            self.assertNotEqual(other["id"], b["id"])

    def test_matching_is_deterministic(self):
        vehicle = {"brand": "پژو", "model": "207", "year": 1401, "starting_price": 1_300_000_000, "transmission": "اتومات"}
        prefs = {
            "preferred_brands": ["پژو"],
            "preferred_models": ["207"],
            "min_year": 1400,
            "max_year": 1403,
            "min_budget": 1_000_000_000,
            "max_budget": 1_500_000_000,
            "preferred_transmission": "اتومات",
            "active": 1,
        }
        self.assertEqual(match_score(vehicle, prefs), match_score(vehicle, prefs))
        self.assertGreater(match_score(vehicle, prefs), 80)


class CancelAndLiveTests(unittest.TestCase):
    def test_cancel_auction_resets_vehicle_and_hides_from_buyers(self):
        tmp, path = _db()
        with tmp:
            when = datetime(2026, 9, 5, 9, 0, 0)
            _appt, vehicle, auction = _pipeline(path, now=when, increment=100)
            _, buyer = _buyer(path, "live@ex.com")
            self.assertEqual(len(svc.buyer_visible_auctions(buyer, path, now=when)), 1)
            cancelled = svc.cancel_auction(auction["id"], db_path=path, now=when)
            self.assertEqual(cancelled["status"], "CANCELLED")
            reset = svc.get_vehicle(vehicle["id"], path)
            self.assertEqual(reset["status"], "READY_FOR_BIDDING")
            self.assertEqual(reset["published_for_bidding"], 0)
            self.assertIsNone(svc.auction_for_vehicle(vehicle["id"], path))
            self.assertEqual(svc.buyer_visible_auctions(buyer, path, now=when), [])
            with self.assertRaises(svc.MarketplaceError):
                svc.place_manual_bid(auction["id"], buyer, 2000, db_path=path, now=when)

    def test_live_revision_bumps_on_bid_and_register(self):
        tmp, path = _db()
        with tmp:
            when = datetime(2026, 9, 5, 9, 0, 0)
            start = svc.live_state(path)["revision"]
            _appt, _vehicle, auction = _pipeline(path, now=when, increment=100)
            after_publish = svc.live_state(path)["revision"]
            self.assertGreater(after_publish, start)
            _, buyer = _buyer(path, "live2@ex.com")
            after_register = svc.live_state(path)["revision"]
            self.assertGreater(after_register, after_publish)
            svc.place_manual_bid(auction["id"], buyer, 1_300_000_000, db_path=path, now=when)
            self.assertGreater(svc.live_state(path)["revision"], after_register)
            svc.cancel_auction(auction["id"], db_path=path, now=when)
            self.assertGreater(svc.live_state(path)["revision"], after_register)


class InspectionCatalogTests(unittest.TestCase):
    def test_body_and_cabin_defaults(self):
        catalog = svc.inspection_catalog()
        labels = {item["label"] for cat in catalog["categories"] for item in cat["items"]}
        self.assertIn("بدنه و شاسی", [cat["label"] for cat in catalog["categories"]])
        self.assertIn("اتاق و کابین", [cat["label"] for cat in catalog["categories"]])
        for needed in ("کاپوت", "شاسی جلو", "درب جلو راننده", "سقف", "وضعیت کلی اتاق"):
            self.assertIn(needed, labels)
        paint = next(field for field in catalog["vehicle_fields"] if field["key"] == "paint_status")
        self.assertIn("رنگ دارد", paint["options"])
        cabin = next(field for field in catalog["vehicle_fields"] if field["key"] == "cabin_condition")
        self.assertIn("سالم", cabin["options"])

    def test_unpublished_hides_inspection_and_published_sends_full_spec(self):
        tmp, path = _db()
        with tmp:
            when = datetime(2026, 9, 5, 9, 0, 0)
            appt = svc.create_appointment("2026-09-05", "10:30", "علی رضایی", "09120000000", db_path=path, now=when)
            vehicle = next(item for item in svc.list_vehicles(path) if item["appointment_id"] == appt["id"])
            _, buyer = _buyer(path, "b@ex.com")
            svc.start_inspection(vehicle["id"], db_path=path, now=when)
            report = {
                "summary": "کاپوت رنگ دارد",
                "strengths": ["کارکرد کم نسبت به سال"],
                "categories": {"body": {"items": {"hood": {"status": "رنگ دارد", "note": ""}}}},
            }
            svc.save_inspection(vehicle["id"], report=report, db_path=path, now=when)
            svc.finalize_inspection(vehicle["id"], "کاپوت رنگ دارد", report=report, db_path=path, now=when)
            svc.update_vehicle(
                vehicle["id"],
                {
                    "brand": "تویوتا",
                    "model": "کرولا",
                    "year": 2025,
                    "mileage": 10,
                    "transmission": "اتومات",
                    "color": "سفید",
                    "paint_status": "رنگ دارد",
                    "cabin_condition": "سالم",
                    "technical_condition": "سالم",
                    "body_type": "سدان",
                    "fuel_type": "هیبرید",
                    "document_type": "تک برگی",
                    "starting_price": 1000,
                    "vin": "SECRETVIN",
                    "plate": "12ب345",
                },
                db_path=path,
                now=when,
            )
            self.assertEqual(svc.buyer_visible_auctions(buyer, path, now=when), [])
            with self.assertRaises(Exception):
                from app.marketplace.privacy import public_vehicle

                public_vehicle(svc.get_vehicle(vehicle["id"], path))
            svc.approve_vehicle(vehicle["id"], db_path=path, now=when)
            self.assertEqual(svc.buyer_visible_auctions(buyer, path, now=when), [])
            auction = svc.publish_vehicle(vehicle["id"], increment=100, db_path=path, now=when)
            self.assertEqual(auction["end_time"], (when + timedelta(seconds=60)).isoformat(timespec="seconds"))
            visible = svc.buyer_visible_auctions(buyer, path, now=when)
            self.assertEqual(len(visible), 1)
            item = visible[0]
            self.assertEqual(item["paint_status"], "رنگ دارد")
            self.assertEqual(item["cabin_condition"], "سالم")
            self.assertEqual(item["fuel_type"], "هیبرید")
            self.assertNotIn("vin", item)
            self.assertNotIn("customer_name", item)
            hood = next(
                row
                for cat in item["inspection"]["categories"]
                if cat["id"] == "body"
                for row in cat["items"]
                if row["id"] == "hood"
            )
            self.assertEqual(hood["status"], "رنگ دارد")
            self.assertFalse(hood["ok"])
            body_cat = next(cat for cat in item["inspection"]["categories"] if cat["id"] == "body")
            self.assertLess(body_cat["score"], 10)
            doors = next(row for cat in item["inspection"]["categories"] if cat["id"] == "body" for row in cat["items"] if row["id"] == "front_driver_door")
            self.assertEqual(doors["status"], "سالم")
            detail = svc.buyer_auction_detail(auction["id"], buyer, db_path=path, now=when)
            self.assertEqual(detail["inspection"]["summary"], "کاپوت رنگ دارد")
            self.assertIn("کارکرد کم نسبت به سال", detail["strengths"])
            self.assertNotIn("SECRETVIN", str(detail))


class DailyLedgerTests(unittest.TestCase):
    def test_ended_auction_has_paginated_bid_list_and_day_nav(self):
        tmp, path = _db()
        with tmp:
            when = datetime(2026, 9, 5, 9, 0, 0)
            _appt, vehicle, auction = _pipeline(path, start=1000, increment=100, now=when)
            session_a, a = _buyer(path, "a@ex.com")
            session_b, b = _buyer(path, "b@ex.com")
            svc.update_buyer_profile(a["id"], {"contact_person": "علی برنده", "phone": "09121111111"}, db_path=path)
            svc.update_buyer_profile(b["id"], {"contact_person": "مریم خریدار", "phone": "09122222222"}, db_path=path)
            svc.place_manual_bid(auction["id"], a, 1000, db_path=path, now=when)
            svc.place_manual_bid(auction["id"], b, 1200, db_path=path, now=when + timedelta(seconds=2))
            closed = svc.close_if_expired(auction["id"], db_path=path, now=when + timedelta(hours=2))
            self.assertEqual(closed["status"], "ENDED")
            report = svc.day_report(when.date(), office=True, db_path=path)
            self.assertEqual(report["day"], "2026-09-05")
            self.assertEqual(report["prev_day"], "2026-09-04")
            self.assertEqual(report["next_day"], "2026-09-06")
            self.assertEqual(report["total_auctions"], 1)
            self.assertGreaterEqual(report["total_bids"], 2)
            self.assertEqual(report["auctions"][0]["vehicle"]["brand"], "پژو")
            self.assertEqual(report["auctions"][0]["winner"]["buyer_name"], "مریم خریدار")
            empty = svc.day_report(when.date() - timedelta(days=1), office=True, db_path=path)
            self.assertEqual(empty["total_auctions"], 0)
            office_page = svc.list_bids_page(auction["id"], office=True, page=1, page_size=1, db_path=path)
            self.assertEqual(office_page["page_size"], 1)
            self.assertGreaterEqual(office_page["pages"], 2)
            self.assertEqual(office_page["items"][0]["buyer_name"], "علی برنده")
            clamped = svc.list_bids_page(auction["id"], office=True, page_size=400, db_path=path)
            self.assertEqual(clamped["page_size"], 50)
            buyer_report = svc.day_report(when.date(), office=False, buyer_id=a["id"], db_path=path)
            self.assertEqual(buyer_report["total_auctions"], 1)
            self.assertIsNone(buyer_report["auctions"][0]["winner"]["buyer_name"])
            self.assertIsNone(buyer_report["auctions"][0]["winner"]["buyer_id"])
            self.assertFalse(buyer_report["auctions"][0]["winner"]["is_mine"])
            buyer_bids = svc.list_bids_page(auction["id"], viewer_buyer_id=a["id"], page_size=20, db_path=path)
            for item in buyer_bids["items"]:
                self.assertNotIn("buyer_id", item)
                self.assertNotIn("buyer_name", item)
                self.assertNotIn("buyer_phone", item)
            stranger_session, stranger = _buyer(path, "c@ex.com")
            other_day = svc.day_report(when.date(), office=False, buyer_id=stranger["id"], db_path=path)
            self.assertEqual(other_day["total_auctions"], 0)
            self.assertFalse(svc.buyer_may_list_bids(stranger, closed, path))
            self.assertTrue(svc.buyer_may_list_bids(a, closed, path))
            self.assertNotIn("SECRETVIN", str(buyer_report))
            self.assertNotIn("علی رضایی", str(buyer_report))

    def test_winner_notifies_buyer_and_office(self):
        tmp, path = _db()
        with tmp:
            when = datetime(2026, 9, 5, 9, 0, 0)
            _appt, _vehicle, auction = _pipeline(path, start=1000, increment=100, now=when)
            _, winner = _buyer(path, "win@ex.com")
            svc.update_buyer_profile(winner["id"], {"contact_person": "برنده تست"}, db_path=path)
            svc.place_manual_bid(auction["id"], winner, 1000, db_path=path, now=when)
            svc.close_if_expired(auction["id"], db_path=path, now=when + timedelta(hours=1))
            notes = svc.list_notifications(winner["user_id"], path)
            self.assertTrue(any(row["event"] == "YOU_WON" and "برنده" in row["title"] for row in notes))
            self.assertTrue(all("buyer_name" not in (row.get("payload") or {}) for row in notes))
            office = svc.user_by_email("office@center.local", path)
            office_notes = svc.list_notifications(office["id"], path, office=True)
            self.assertTrue(any(row["event"] == "WINNER_READY" and "برنده تست" in row["body"] for row in office_notes))
            pending = [row for row in svc.list_winners(path) if row["status"] == "PENDING_OFFICE_CONFIRMATION"]
            self.assertEqual(pending[0]["buyer_name"], "برنده تست")
            self.assertTrue(pending[0].get("brand"))
            marked = svc.mark_notifications_read(winner["user_id"], db_path=path)
            self.assertEqual(marked["unread"], 0)

    def test_office_calendar_is_jalali(self):
        cal = svc.office_month_calendar(1405, 6)
        self.assertEqual(cal["month_name"], "شهریور")
        self.assertIn("09", cal["hours"])
        self.assertEqual(cal["minutes"], ["00", "15", "30", "45"])
        self.assertIn("09:15", cal["times"])
        labeled = next(cell for week in cal["weeks"] for cell in week if cell)
        self.assertIn("jalali", labeled)
        self.assertNotIn("/", labeled["jalali"])
        self.assertTrue(any(cell and cell.get("friday") for week in cal["weeks"] for cell in week))


@unittest.skipUnless(TestClient, "httpx is required")
class MarketplaceApiTests(unittest.TestCase):
    def test_http_auth_and_privacy(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        reset_state(root, db_path=root / "book.sqlite")
        client = TestClient(app)
        missing = client.post("/auth/register", json={"email": "a@ex.com", "password": "Secret123", "business_name": "A"})
        self.assertEqual(missing.status_code, 400)
        client.post(
            "/auth/register",
            json={
                "email": "a@ex.com",
                "password": "Secret123",
                "full_name": "علی رضایی",
                "phone": "09121234567",
                "national_id": "0012345678",
                "business_name": "A",
            },
        )
        denied = client.post("/auth/login", json={"email": "a@ex.com", "password": "nope"})
        self.assertEqual(denied.status_code, 401)
        login = client.post("/auth/login", json={"email": "a@ex.com", "password": "Secret123"}).json()
        token = login["token"]
        me = client.get("/buyers/me", headers={"Authorization": "Bearer " + token}).json()
        self.assertEqual(me["buyer"]["contact_person"], "علی رضایی")
        self.assertEqual(me["buyer"]["phone"], "09121234567")
        self.assertEqual(me["buyer"]["national_id"], "0012345678")
        self.assertTrue(me["buyer"]["id"])
        buyer_id = me["buyer"]["id"]
        edited = client.put(
            "/buyers/me",
            json={"contact_person": "سارا محمدی", "phone": "09120001111", "city": "اصفهان"},
            headers={"Authorization": "Bearer " + token},
        ).json()
        self.assertEqual(edited["contact_person"], "سارا محمدی")
        self.assertEqual(edited["city"], "اصفهان")
        office = client.post("/auth/login", json={"email": "office@center.local", "password": "Office123!"}).json()
        office_h = {"Authorization": "Bearer " + office["token"]}
        buyer_h = {"Authorization": "Bearer " + token}
        office_edit = client.put(
            f"/office/buyers/{buyer_id}",
            json={"contact_person": "نرگس کریمی", "phone": "09125556677"},
            headers=office_h,
        ).json()
        self.assertEqual(office_edit["contact_person"], "نرگس کریمی")
        denied_edit = client.put(f"/office/buyers/{buyer_id}", json={"contact_person": "هکر"}, headers=buyer_h)
        self.assertEqual(denied_edit.status_code, 403)
        buyers = client.get("/office/dashboard", headers=office_h).json()["buyers"]
        buyer_id = buyers[0]["id"]
        client.post(f"/office/buyers/{buyer_id}/status", json={"status": "ACTIVE", "verification_status": "VERIFIED"}, headers=office_h)
        appt = client.post("/office/appointments", json={"date": "2026-09-05", "time": "10:30", "customer_name": "علی", "customer_phone": "0912"}, headers=office_h).json()
        schedule = client.get("/buyer/appointments", headers=buyer_h).json()
        self.assertTrue(all("customer_name" not in row for row in schedule))
        self.assertTrue(any(row["time"] == "10:30" for row in schedule))
        other = client.get(f"/buyers/{buyer_id}", headers=buyer_h)
        self.assertEqual(other.status_code, 403)
        office_page = client.get("/office/dashboard", headers=buyer_h)
        self.assertEqual(office_page.status_code, 403)
        vehicle_id = client.get("/office/dashboard", headers=office_h).json()["vehicles"][0]["id"]
        secret = client.get(f"/office/vehicles/{vehicle_id}", headers=buyer_h)
        self.assertEqual(secret.status_code, 403)
        self.assertEqual(client.get("/auctions", headers=buyer_h).json(), [])
        catalog = client.get("/inspection-catalog", headers=office_h).json()
        self.assertTrue(any(cat["id"] == "body" for cat in catalog["categories"]))
        client.post(f"/office/vehicles/{vehicle_id}/inspect", headers=office_h)
        client.put(
            f"/office/vehicles/{vehicle_id}",
            json={"brand": "تویوتا", "model": "کرولا", "paint_status": "رنگ دارد", "cabin_condition": "سالم", "starting_price": 1000},
            headers=office_h,
        )
        client.post(
            f"/office/vehicles/{vehicle_id}/finalize-inspection",
            json={"summary": "کاپوت رنگ دارد", "report": {"categories": {"body": {"items": {"hood": {"status": "رنگ دارد"}}}}}},
            headers=office_h,
        )
        client.post(f"/office/vehicles/{vehicle_id}/approve", headers=office_h)
        self.assertEqual(client.get("/auctions", headers=buyer_h).json(), [])
        client.post(f"/office/vehicles/{vehicle_id}/publish", json={}, headers=office_h)
        listed = client.get("/auctions", headers=buyer_h).json()
        self.assertEqual(listed[0]["paint_status"], "رنگ دارد")
        hood = next(row for cat in listed[0]["inspection"]["categories"] if cat["id"] == "body" for row in cat["items"] if row["id"] == "hood")
        self.assertEqual(hood["status"], "رنگ دارد")
        self.assertNotIn("customer_name", listed[0])
        tmp.cleanup()


class ArchiveAndPersistenceTests(unittest.TestCase):
    def test_finished_inspection_is_kept_with_owner_contact(self):
        tmp, path = _db()
        with tmp:
            when = datetime(2026, 9, 5, 9, 0, 0)
            appt = svc.create_appointment(
                "2026-09-05",
                "10:30",
                "علی رضایی",
                "09120000000",
                db_path=path,
                now=when,
            )
            vehicle = next(item for item in svc.list_vehicles(path) if item["appointment_id"] == appt["id"])
            svc.start_inspection(vehicle["id"], db_path=path, now=when)
            saved = svc.finalize_inspection(vehicle["id"], "سالم", db_path=path, now=when)
            self.assertTrue(saved["inspection_completed"])
            self.assertEqual(saved["customer_name"], "علی رضایی")
            self.assertEqual(saved["customer_phone"], "09120000000")
            archive = svc.list_inspected_vehicles(path)
            self.assertEqual(len(archive), 1)
            self.assertEqual(archive[0]["customer_name"], "علی رضایی")
            self.assertEqual(archive[0]["customer_phone"], "09120000000")
            self.assertNotIn("vin", archive[0])
            dash = svc.office_dashboard(path, now=when)
            self.assertEqual(dash["archive"][0]["customer_phone"], "09120000000")

    def test_existing_sqlite_survives_path_upgrade(self):
        import app.booking as booking

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo_data = root / "data"
            durable = root / "appdata"
            repo_data.mkdir()
            src = repo_data / "bookings.sqlite"
            src.write_text("saved-records", encoding="utf-8")
            previous = booking.DATA_DIR
            previous_db = os.environ.pop("PERSIAN_TYPE_DB", None)
            previous_data = os.environ.pop("PERSIAN_TYPE_DATA", None)
            try:
                booking.DATA_DIR = repo_data
                os.environ["PERSIAN_TYPE_DATA"] = str(durable)
                path = booking.default_db_path()
                self.assertEqual(path, durable / "bookings.sqlite")
                self.assertEqual(path.read_text(encoding="utf-8"), "saved-records")
                src.write_text("changed-in-repo", encoding="utf-8")
                again = booking.default_db_path()
                self.assertEqual(again.read_text(encoding="utf-8"), "saved-records")
            finally:
                booking.DATA_DIR = previous
                if previous_db is None:
                    os.environ.pop("PERSIAN_TYPE_DB", None)
                else:
                    os.environ["PERSIAN_TYPE_DB"] = previous_db
                if previous_data is None:
                    os.environ.pop("PERSIAN_TYPE_DATA", None)
                else:
                    os.environ["PERSIAN_TYPE_DATA"] = previous_data

    def test_adopts_repo_records_when_durable_db_is_empty(self):
        import app.booking as booking

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo_data = root / "data"
            durable = root / "appdata"
            repo_data.mkdir()
            repo_db = repo_data / "bookings.sqlite"
            empty = durable / "bookings.sqlite"
            svc.bootstrap(repo_db)
            svc.create_appointment("2026-09-05", "10:30", "مریم", "09125550000", db_path=repo_db)
            svc.bootstrap(empty)
            self.assertGreater(booking.sqlite_record_count(repo_db), booking.sqlite_record_count(empty))
            previous = booking.DATA_DIR
            previous_db = os.environ.pop("PERSIAN_TYPE_DB", None)
            previous_data = os.environ.pop("PERSIAN_TYPE_DATA", None)
            try:
                booking.DATA_DIR = repo_data
                os.environ["PERSIAN_TYPE_DATA"] = str(durable)
                path = booking.default_db_path()
                self.assertEqual(path, empty)
                self.assertGreaterEqual(booking.sqlite_record_count(path), booking.sqlite_record_count(repo_db))
                self.assertTrue((durable / "backups").exists())
            finally:
                booking.DATA_DIR = previous
                if previous_db is None:
                    os.environ.pop("PERSIAN_TYPE_DB", None)
                else:
                    os.environ["PERSIAN_TYPE_DB"] = previous_db
                if previous_data is None:
                    os.environ.pop("PERSIAN_TYPE_DATA", None)
                else:
                    os.environ["PERSIAN_TYPE_DATA"] = previous_data


if __name__ == "__main__":
    unittest.main()
