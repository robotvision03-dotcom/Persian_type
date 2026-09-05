"""SQLite schema for the buyer portal and bid engine."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..booking import default_db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS password_resets (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS buyer_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,
    business_name TEXT NOT NULL DEFAULT '',
    contact_person TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    national_id TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    dealer_type TEXT NOT NULL DEFAULT '',
    tax_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'PENDING',
    verification_status TEXT NOT NULL DEFAULT 'UNVERIFIED',
    reputation_score INTEGER NOT NULL DEFAULT 0,
    total_bids INTEGER NOT NULL DEFAULT 0,
    winning_bids INTEGER NOT NULL DEFAULT 0,
    completed_transactions INTEGER NOT NULL DEFAULT 0,
    cancelled_transactions INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS buyer_preferences (
    buyer_id INTEGER PRIMARY KEY,
    preferred_brands TEXT NOT NULL DEFAULT '[]',
    preferred_models TEXT NOT NULL DEFAULT '[]',
    min_year INTEGER,
    max_year INTEGER,
    min_budget INTEGER,
    max_budget INTEGER,
    preferred_cities TEXT NOT NULL DEFAULT '[]',
    preferred_transmission TEXT NOT NULL DEFAULT '',
    preferred_body_types TEXT NOT NULL DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (buyer_id) REFERENCES buyer_profiles(id)
);
CREATE TABLE IF NOT EXISTS marketplace_appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_appointment_id INTEGER,
    customer_name TEXT NOT NULL DEFAULT '',
    customer_phone TEXT NOT NULL DEFAULT '',
    date TEXT NOT NULL,
    time TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'SCHEDULED',
    source TEXT NOT NULL DEFAULT 'OFFICE',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    appointment_id INTEGER,
    status TEXT NOT NULL DEFAULT 'APPOINTMENT_SCHEDULED',
    brand TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    year INTEGER,
    mileage INTEGER,
    transmission TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '',
    body_type TEXT NOT NULL DEFAULT '',
    body_condition TEXT NOT NULL DEFAULT '',
    paint_status TEXT NOT NULL DEFAULT '',
    cabin_condition TEXT NOT NULL DEFAULT '',
    technical_condition TEXT NOT NULL DEFAULT '',
    fuel_type TEXT NOT NULL DEFAULT '',
    engine TEXT NOT NULL DEFAULT '',
    document_type TEXT NOT NULL DEFAULT '',
    insurance_months INTEGER,
    strengths TEXT NOT NULL DEFAULT '[]',
    inspection_summary TEXT NOT NULL DEFAULT '',
    photos TEXT NOT NULL DEFAULT '[]',
    starting_price INTEGER NOT NULL DEFAULT 0,
    reserve_price INTEGER,
    customer_name TEXT NOT NULL DEFAULT '',
    customer_phone TEXT NOT NULL DEFAULT '',
    customer_address TEXT NOT NULL DEFAULT '',
    vin TEXT NOT NULL DEFAULT '',
    plate TEXT NOT NULL DEFAULT '',
    inspection_completed INTEGER NOT NULL DEFAULT 0,
    office_approved INTEGER NOT NULL DEFAULT 0,
    published_for_bidding INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (appointment_id) REFERENCES marketplace_appointments(id)
);
CREATE TABLE IF NOT EXISTS inspections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'IN_PROGRESS',
    summary TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    report_json TEXT NOT NULL DEFAULT '{}',
    finalized_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id)
);
CREATE TABLE IF NOT EXISTS auctions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'SCHEDULED',
    start_time TEXT,
    end_time TEXT,
    starting_price INTEGER NOT NULL,
    reserve_price INTEGER,
    bid_increment INTEGER NOT NULL,
    current_price INTEGER NOT NULL,
    current_winner_id INTEGER,
    published_at TEXT,
    participant_policy TEXT NOT NULL DEFAULT 'ALL_VERIFIED_BUYERS',
    anti_sniping_enabled INTEGER NOT NULL DEFAULT 1,
    extension_window_seconds INTEGER NOT NULL DEFAULT 120,
    extension_seconds INTEGER NOT NULL DEFAULT 120,
    maximum_extensions INTEGER NOT NULL DEFAULT 3,
    extensions_used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    ledger_day TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (vehicle_id) REFERENCES vehicles(id)
);
CREATE TABLE IF NOT EXISTS auction_participants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    auction_id INTEGER NOT NULL,
    buyer_id INTEGER NOT NULL,
    match_score INTEGER NOT NULL DEFAULT 0,
    invited_at TEXT NOT NULL,
    joined_at TEXT,
    status TEXT NOT NULL DEFAULT 'INVITED',
    UNIQUE (auction_id, buyer_id),
    FOREIGN KEY (auction_id) REFERENCES auctions(id),
    FOREIGN KEY (buyer_id) REFERENCES buyer_profiles(id)
);
CREATE TABLE IF NOT EXISTS bids (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    auction_id INTEGER NOT NULL,
    buyer_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    bid_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACCEPTED',
    request_id TEXT,
    FOREIGN KEY (auction_id) REFERENCES auctions(id),
    FOREIGN KEY (buyer_id) REFERENCES buyer_profiles(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bids_request_id
    ON bids(request_id) WHERE request_id IS NOT NULL AND request_id != '';
CREATE TABLE IF NOT EXISTS auto_bid_limits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    auction_id INTEGER NOT NULL,
    buyer_id INTEGER NOT NULL,
    max_bid INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (auction_id, buyer_id),
    FOREIGN KEY (auction_id) REFERENCES auctions(id),
    FOREIGN KEY (buyer_id) REFERENCES buyer_profiles(id)
);
CREATE TABLE IF NOT EXISTS auction_winners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    auction_id INTEGER NOT NULL UNIQUE,
    buyer_id INTEGER NOT NULL,
    final_price INTEGER NOT NULL,
    reserve_met INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING_OFFICE_CONFIRMATION',
    created_at TEXT NOT NULL,
    FOREIGN KEY (auction_id) REFERENCES auctions(id),
    FOREIGN KEY (buyer_id) REFERENCES buyer_profiles(id)
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    event TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',
    read_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS marketplace_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bids_auction_created ON bids(auction_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_bids_buyer_created ON bids(buyer_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_auctions_day ON auctions(end_time, status);
CREATE INDEX IF NOT EXISTS idx_auctions_vehicle ON auctions(vehicle_id, status);
CREATE INDEX IF NOT EXISTS idx_winners_buyer ON auction_winners(buyer_id, created_at);
CREATE INDEX IF NOT EXISTS idx_appointments_day ON marketplace_appointments(date, time);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications(user_id, read_at, id);
"""


VEHICLE_EXTRA_COLUMNS = {
    "paint_status": "TEXT NOT NULL DEFAULT ''",
    "cabin_condition": "TEXT NOT NULL DEFAULT ''",
    "technical_condition": "TEXT NOT NULL DEFAULT ''",
    "fuel_type": "TEXT NOT NULL DEFAULT ''",
    "engine": "TEXT NOT NULL DEFAULT ''",
    "document_type": "TEXT NOT NULL DEFAULT ''",
    "insurance_months": "INTEGER",
    "strengths": "TEXT NOT NULL DEFAULT '[]'",
}

INSPECTION_EXTRA_COLUMNS = {
    "report_json": "TEXT NOT NULL DEFAULT '{}'",
}

BUYER_EXTRA_COLUMNS = {
    "national_id": "TEXT NOT NULL DEFAULT ''",
}

APPOINTMENT_EXTRA_COLUMNS = {
    "source": "TEXT NOT NULL DEFAULT 'OFFICE'",
    "notes": "TEXT NOT NULL DEFAULT ''",
}

AUCTION_EXTRA_COLUMNS = {
    "ledger_day": "TEXT NOT NULL DEFAULT ''",
}

PIPELINE_VEHICLE_STATUSES = (
    "APPOINTMENT_SCHEDULED",
    "CUSTOMER_ARRIVED",
    "INSPECTION_IN_PROGRESS",
    "INSPECTION_COMPLETED",
    "PENDING_OFFICE_APPROVAL",
    "READY_FOR_BIDDING",
    "BIDDING_ACTIVE",
    "BIDDING_ENDED",
    "AUCTION_SUSPENDED",
)


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, ddl in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_bids_auction_created ON bids(auction_id, created_at, id)",
    "CREATE INDEX IF NOT EXISTS idx_bids_buyer_created ON bids(buyer_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_auctions_day ON auctions(end_time, status)",
    "CREATE INDEX IF NOT EXISTS idx_auctions_ledger_day ON auctions(ledger_day, status, id)",
    "CREATE INDEX IF NOT EXISTS idx_auctions_vehicle ON auctions(vehicle_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_winners_buyer ON auction_winners(buyer_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_appointments_day ON marketplace_appointments(date, time)",
    "CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications(user_id, read_at, id)",
)


def migrate_marketplace(conn: sqlite3.Connection) -> None:
    _ensure_columns(conn, "vehicles", VEHICLE_EXTRA_COLUMNS)
    _ensure_columns(conn, "inspections", INSPECTION_EXTRA_COLUMNS)
    _ensure_columns(conn, "buyer_profiles", BUYER_EXTRA_COLUMNS)
    _ensure_columns(conn, "marketplace_appointments", APPOINTMENT_EXTRA_COLUMNS)
    _ensure_columns(conn, "auctions", AUCTION_EXTRA_COLUMNS)
    conn.execute(
        """
        UPDATE auctions
        SET ledger_day = substr(COALESCE(end_time, published_at, created_at), 1, 10)
        WHERE ledger_day IS NULL OR ledger_day = ''
        """
    )
    for sql in INDEXES:
        conn.execute(sql)


def init_marketplace(db_path: Path | None = None) -> Path:
    path = db_path or default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with get_conn(path) as conn:
        conn.executescript(SCHEMA)
        migrate_marketplace(conn)
    return path


@contextmanager
def get_conn(db_path: Path | None = None, immediate: bool = False) -> Iterator[sqlite3.Connection]:
    path = db_path or default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        if immediate:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
