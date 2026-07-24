#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Thin sqlite3 helper layer.

The environment this app was rebuilt in has no internet access to install
Flask-SQLAlchemy / Flask-Login, so persistence is done directly with
Python's built-in sqlite3 module instead of an ORM. models.py builds
small, ordinary Python objects on top of the queries defined here.
"""

import sqlite3
from flask import g

DB_PATH = "routeboard.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'passenger',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS drivers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
    license_no TEXT NOT NULL,
    on_duty INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS buses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bus_number TEXT UNIQUE NOT NULL,
    capacity INTEGER NOT NULL DEFAULT 40,
    driver_id INTEGER REFERENCES drivers(id),
    current_lat REAL,
    current_lng REAL,
    location_updated_at TEXT
);

CREATE TABLE IF NOT EXISTS gps_pings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bus_id INTEGER REFERENCES buses(id),
    driver_id INTEGER REFERENCES drivers(id),
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    sent_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS routes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    origin TEXT NOT NULL,
    destination TEXT NOT NULL,
    distance_km REAL NOT NULL,
    duration_min INTEGER NOT NULL,
    base_fare REAL NOT NULL,
    color TEXT NOT NULL DEFAULT '#2F7A6F'
);

CREATE TABLE IF NOT EXISTS trips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id INTEGER NOT NULL REFERENCES routes(id),
    bus_id INTEGER NOT NULL REFERENCES buses(id),
    departure_time TEXT NOT NULL,
    seats_booked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id INTEGER NOT NULL REFERENCES trips(id),
    passenger_id INTEGER NOT NULL REFERENCES users(id),
    seat_no INTEGER NOT NULL,
    fare REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    booked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER UNIQUE NOT NULL REFERENCES tickets(id),
    amount REAL NOT NULL,
    method TEXT NOT NULL DEFAULT 'card',
    status TEXT NOT NULL DEFAULT 'pending',
    paid_at TEXT
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    message TEXT NOT NULL,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
