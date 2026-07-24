#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Domain models for the RouteBoard bus ticketing system.

This file replaces the original stub files (admin.py, bus.py, driver.py,
gPSDevice.py, notification.py, passenger.py, payment.py, route.py, ticket.py,
uSER.py). Those files did not run as-is: class/method names contained spaces
("GPS device", "manage routes", "share location"), one used an invalid type
annotation (self.payment id / string), and every method body was an empty
"pass" with no persistence layer behind it. The classes are rebuilt here as
plain Python objects, backed directly by sqlite3 (see db.py), with valid
names, working relationships, and the actual logic the method stubs implied.

class1.py and class5.py contained no fields or behavior, so there was
nothing domain-specific to preserve from them.
"""

from datetime import datetime

from werkzeug.security import generate_password_hash, check_password_hash

from db import get_db

ROLE_ADMIN = "admin"
ROLE_DRIVER = "driver"
ROLE_PASSENGER = "passenger"


def _now():
    return datetime.utcnow().isoformat(timespec="seconds")


def _parse_dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


# ---------------------------------------------------------------------------
# User  (replaces uSER.py)
# ---------------------------------------------------------------------------

class User:
    def __init__(self, id, name, email, password_hash, role, created_at):
        self.id = id
        self.name = name
        self.email = email
        self.password_hash = password_hash
        self.role = role
        self.created_at = _parse_dt(created_at)

    # -- Flask-Login style helpers (session-based auth uses these too) --
    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def get_id(self):
        return str(self.id)

    @property
    def is_admin(self):
        return self.role == ROLE_ADMIN

    @property
    def is_driver(self):
        return self.role == ROLE_DRIVER

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    @property
    def driver_profile(self):
        return Driver.get_by_user_id(self.id)

    @staticmethod
    def _from_row(row):
        if row is None:
            return None
        return User(row["id"], row["name"], row["email"], row["password_hash"],
                    row["role"], row["created_at"])

    @classmethod
    def get(cls, user_id):
        row = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return cls._from_row(row)

    @classmethod
    def get_by_email(cls, email):
        row = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return cls._from_row(row)

    @classmethod
    def count(cls):
        return get_db().execute("SELECT COUNT(*) c FROM users").fetchone()["c"]

    @classmethod
    def all_by_role(cls, role):
        rows = get_db().execute("SELECT * FROM users WHERE role = ?", (role,)).fetchall()
        return [cls._from_row(r) for r in rows]

    @classmethod
    def create(cls, name, email, role=ROLE_PASSENGER):
        db = get_db()
        cur = db.execute(
            "INSERT INTO users (name, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (name, email, "", role, _now()),
        )
        db.commit()
        return cls.get(cur.lastrowid)

    def save(self):
        db = get_db()
        db.execute(
            "UPDATE users SET name=?, email=?, password_hash=?, role=? WHERE id=?",
            (self.name, self.email, self.password_hash, self.role, self.id),
        )
        db.commit()

    def __repr__(self):
        return f"<User {self.email} ({self.role})>"


# ---------------------------------------------------------------------------
# Driver  (replaces driver.py)
# ---------------------------------------------------------------------------

class Driver:
    def __init__(self, id, user_id, license_no, on_duty):
        self.id = id
        self.user_id = user_id
        self.license_no = license_no
        self.on_duty = bool(on_duty)
        self._user = None
        self._bus = None

    @property
    def user(self):
        if self._user is None:
            self._user = User.get(self.user_id)
        return self._user

    @property
    def bus(self):
        if self._bus is None:
            row = get_db().execute("SELECT * FROM buses WHERE driver_id = ?", (self.id,)).fetchone()
            self._bus = Bus._from_row(row)
        return self._bus

    @staticmethod
    def _from_row(row):
        if row is None:
            return None
        return Driver(row["id"], row["user_id"], row["license_no"], row["on_duty"])

    @classmethod
    def get(cls, driver_id):
        row = get_db().execute("SELECT * FROM drivers WHERE id = ?", (driver_id,)).fetchone()
        return cls._from_row(row)

    @classmethod
    def get_by_user_id(cls, user_id):
        row = get_db().execute("SELECT * FROM drivers WHERE user_id = ?", (user_id,)).fetchone()
        return cls._from_row(row)

    @classmethod
    def all(cls):
        rows = get_db().execute("SELECT * FROM drivers").fetchall()
        return [cls._from_row(r) for r in rows]

    @classmethod
    def create(cls, user_id, license_no, on_duty=False):
        db = get_db()
        cur = db.execute(
            "INSERT INTO drivers (user_id, license_no, on_duty) VALUES (?, ?, ?)",
            (user_id, license_no, int(on_duty)),
        )
        db.commit()
        return cls.get(cur.lastrowid)

    def save(self):
        db = get_db()
        db.execute("UPDATE drivers SET license_no=?, on_duty=? WHERE id=?",
                    (self.license_no, int(self.on_duty), self.id))
        db.commit()

    def share_location(self, lat, lng):
        """Records a GPS ping and updates the assigned bus's live position."""
        db = get_db()
        bus = self.bus
        db.execute(
            "INSERT INTO gps_pings (bus_id, driver_id, lat, lng, sent_at) VALUES (?, ?, ?, ?, ?)",
            (bus.id if bus else None, self.id, lat, lng, _now()),
        )
        if bus:
            bus.update_location(lat, lng)
        db.commit()

    def send_emergency_alert(self, message="Emergency reported by driver"):
        """Pushes an emergency notification to every admin."""
        for admin_user in User.all_by_role(ROLE_ADMIN):
            Notification.create(admin_user.id, message)

    def __repr__(self):
        return f"<Driver {self.license_no}>"


# ---------------------------------------------------------------------------
# Bus  (replaces bus.py, folds in gPSDevice.py's "send location")
# ---------------------------------------------------------------------------

class Bus:
    def __init__(self, id, bus_number, capacity, driver_id, current_lat, current_lng, location_updated_at):
        self.id = id
        self.bus_number = bus_number
        self.capacity = capacity
        self.driver_id = driver_id
        self.current_lat = current_lat
        self.current_lng = current_lng
        self.location_updated_at = _parse_dt(location_updated_at)
        self._driver = None

    @property
    def driver(self):
        if self._driver is None and self.driver_id:
            self._driver = Driver.get(self.driver_id)
        return self._driver

    @staticmethod
    def _from_row(row):
        if row is None:
            return None
        return Bus(row["id"], row["bus_number"], row["capacity"], row["driver_id"],
                    row["current_lat"], row["current_lng"], row["location_updated_at"])

    @classmethod
    def get(cls, bus_id):
        row = get_db().execute("SELECT * FROM buses WHERE id = ?", (bus_id,)).fetchone()
        return cls._from_row(row)

    @classmethod
    def all(cls):
        rows = get_db().execute("SELECT * FROM buses").fetchall()
        return [cls._from_row(r) for r in rows]

    @classmethod
    def count(cls):
        return get_db().execute("SELECT COUNT(*) c FROM buses").fetchone()["c"]

    @classmethod
    def create(cls, bus_number, capacity=40, driver_id=None, current_lat=None, current_lng=None):
        db = get_db()
        cur = db.execute(
            "INSERT INTO buses (bus_number, capacity, driver_id, current_lat, current_lng, location_updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (bus_number, capacity, driver_id, current_lat, current_lng,
             _now() if current_lat is not None else None),
        )
        db.commit()
        return cls.get(cur.lastrowid)

    def update_location(self, lat, lng):
        self.current_lat = lat
        self.current_lng = lng
        self.location_updated_at = datetime.utcnow()
        db = get_db()
        db.execute("UPDATE buses SET current_lat=?, current_lng=?, location_updated_at=? WHERE id=?",
                    (lat, lng, _now(), self.id))
        db.commit()

    def __repr__(self):
        return f"<Bus {self.bus_number}>"


# ---------------------------------------------------------------------------
# Route  (replaces route.py)
# ---------------------------------------------------------------------------

class Route:
    def __init__(self, id, code, name, origin, destination, distance_km, duration_min, base_fare, color):
        self.id = id
        self.code = code
        self.name = name
        self.origin = origin
        self.destination = destination
        self.distance_km = distance_km
        self.duration_min = duration_min
        self.base_fare = base_fare
        self.color = color

    def calculate_fare(self, seats=1):
        return round(self.base_fare * seats, 2)

    @staticmethod
    def _from_row(row):
        if row is None:
            return None
        return Route(row["id"], row["code"], row["name"], row["origin"], row["destination"],
                     row["distance_km"], row["duration_min"], row["base_fare"], row["color"])

    @classmethod
    def get(cls, route_id):
        row = get_db().execute("SELECT * FROM routes WHERE id = ?", (route_id,)).fetchone()
        return cls._from_row(row)

    @classmethod
    def all(cls):
        rows = get_db().execute("SELECT * FROM routes").fetchall()
        return [cls._from_row(r) for r in rows]

    @classmethod
    def count(cls):
        return get_db().execute("SELECT COUNT(*) c FROM routes").fetchone()["c"]

    @classmethod
    def search(cls, origin="", destination=""):
        query = "SELECT * FROM routes WHERE 1=1"
        params = []
        if origin:
            query += " AND origin LIKE ?"
            params.append(f"%{origin}%")
        if destination:
            query += " AND destination LIKE ?"
            params.append(f"%{destination}%")
        rows = get_db().execute(query, params).fetchall()
        return [cls._from_row(r) for r in rows]

    @classmethod
    def create(cls, code, name, origin, destination, distance_km, duration_min, base_fare, color):
        db = get_db()
        cur = db.execute(
            "INSERT INTO routes (code, name, origin, destination, distance_km, duration_min, base_fare, color) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (code, name, origin, destination, distance_km, duration_min, base_fare, color),
        )
        db.commit()
        return cls.get(cur.lastrowid)

    def __repr__(self):
        return f"<Route {self.code} {self.origin}->{self.destination}>"


# ---------------------------------------------------------------------------
# Trip  (new — connects Route + Bus + a departure time + seat availability;
# route.py alone had no notion of a timetable, so nothing was actually
# bookable without this)
# ---------------------------------------------------------------------------

class Trip:
    def __init__(self, id, route_id, bus_id, departure_time, seats_booked):
        self.id = id
        self.route_id = route_id
        self.bus_id = bus_id
        self.departure_time = _parse_dt(departure_time)
        self.seats_booked = seats_booked
        self._route = None
        self._bus = None

    @property
    def route(self):
        if self._route is None:
            self._route = Route.get(self.route_id)
        return self._route

    @property
    def bus(self):
        if self._bus is None:
            self._bus = Bus.get(self.bus_id)
        return self._bus

    @property
    def seats_available(self):
        return max(self.bus.capacity - self.seats_booked, 0)

    @staticmethod
    def _from_row(row):
        if row is None:
            return None
        return Trip(row["id"], row["route_id"], row["bus_id"], row["departure_time"], row["seats_booked"])

    @classmethod
    def get(cls, trip_id):
        row = get_db().execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()
        return cls._from_row(row)

    @classmethod
    def upcoming_for_route(cls, route_id):
        rows = get_db().execute(
            "SELECT * FROM trips WHERE route_id = ? AND departure_time >= ? ORDER BY departure_time",
            (route_id, _now()),
        ).fetchall()
        return [cls._from_row(r) for r in rows]

    @classmethod
    def upcoming_for_bus(cls, bus_id):
        rows = get_db().execute(
            "SELECT * FROM trips WHERE bus_id = ? AND departure_time >= ? ORDER BY departure_time",
            (bus_id, _now()),
        ).fetchall()
        return [cls._from_row(r) for r in rows]

    @classmethod
    def latest_for_bus(cls, bus_id):
        row = get_db().execute(
            "SELECT * FROM trips WHERE bus_id = ? ORDER BY departure_time DESC LIMIT 1", (bus_id,)
        ).fetchone()
        return cls._from_row(row)

    @classmethod
    def create(cls, route_id, bus_id, departure_time):
        db = get_db()
        cur = db.execute(
            "INSERT INTO trips (route_id, bus_id, departure_time, seats_booked) VALUES (?, ?, ?, 0)",
            (route_id, bus_id, departure_time.isoformat(timespec="seconds")),
        )
        db.commit()
        return cls.get(cur.lastrowid)

    def increment_seats(self):
        self.seats_booked += 1
        db = get_db()
        db.execute("UPDATE trips SET seats_booked=? WHERE id=?", (self.seats_booked, self.id))
        db.commit()

    def decrement_seats(self):
        self.seats_booked = max(self.seats_booked - 1, 0)
        db = get_db()
        db.execute("UPDATE trips SET seats_booked=? WHERE id=?", (self.seats_booked, self.id))
        db.commit()

    def __repr__(self):
        return f"<Trip route={self.route_id} @ {self.departure_time}>"


# ---------------------------------------------------------------------------
# Ticket  (replaces ticket.py / passenger.py's book_ticket & cancel_ticket)
# ---------------------------------------------------------------------------

class Ticket:
    def __init__(self, id, trip_id, passenger_id, seat_no, fare, status, booked_at):
        self.id = id
        self.trip_id = trip_id
        self.passenger_id = passenger_id
        self.seat_no = seat_no
        self.fare = fare
        self.status = status
        self.booked_at = _parse_dt(booked_at)
        self._trip = None
        self._passenger = None
        self._payment = None

    @property
    def trip(self):
        if self._trip is None:
            self._trip = Trip.get(self.trip_id)
        return self._trip

    @property
    def passenger(self):
        if self._passenger is None:
            self._passenger = User.get(self.passenger_id)
        return self._passenger

    @property
    def payment(self):
        if self._payment is None:
            self._payment = Payment.get_by_ticket_id(self.id)
        return self._payment

    @staticmethod
    def _from_row(row):
        if row is None:
            return None
        return Ticket(row["id"], row["trip_id"], row["passenger_id"], row["seat_no"],
                      row["fare"], row["status"], row["booked_at"])

    @classmethod
    def get(cls, ticket_id):
        row = get_db().execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        return cls._from_row(row)

    @classmethod
    def for_passenger(cls, passenger_id):
        rows = get_db().execute(
            "SELECT * FROM tickets WHERE passenger_id = ? ORDER BY booked_at DESC", (passenger_id,)
        ).fetchall()
        return [cls._from_row(r) for r in rows]

    @classmethod
    def count_confirmed(cls):
        return get_db().execute(
            "SELECT COUNT(*) c FROM tickets WHERE status = 'confirmed'"
        ).fetchone()["c"]

    @classmethod
    def create(cls, trip_id, passenger_id, seat_no, fare, status="pending"):
        db = get_db()
        cur = db.execute(
            "INSERT INTO tickets (trip_id, passenger_id, seat_no, fare, status, booked_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (trip_id, passenger_id, seat_no, fare, status, _now()),
        )
        db.commit()
        return cls.get(cur.lastrowid)

    def set_status(self, status):
        self.status = status
        db = get_db()
        db.execute("UPDATE tickets SET status=? WHERE id=?", (status, self.id))
        db.commit()

    def cancel(self):
        if self.status != "cancelled":
            self.set_status("cancelled")
            self.trip.decrement_seats()

    def __repr__(self):
        return f"<Ticket #{self.id} seat {self.seat_no} ({self.status})>"


# ---------------------------------------------------------------------------
# Payment  (replaces payment.py — fixed the invalid `self.payment id` attribute)
# ---------------------------------------------------------------------------

class Payment:
    def __init__(self, id, ticket_id, amount, method, status, paid_at):
        self.id = id
        self.ticket_id = ticket_id
        self.amount = amount
        self.method = method
        self.status = status
        self.paid_at = _parse_dt(paid_at)
        self._ticket = None

    @property
    def ticket(self):
        if self._ticket is None:
            self._ticket = Ticket.get(self.ticket_id)
        return self._ticket

    @staticmethod
    def _from_row(row):
        if row is None:
            return None
        return Payment(row["id"], row["ticket_id"], row["amount"], row["method"],
                       row["status"], row["paid_at"])

    @classmethod
    def get(cls, payment_id):
        row = get_db().execute("SELECT * FROM payments WHERE id = ?", (payment_id,)).fetchone()
        return cls._from_row(row)

    @classmethod
    def get_by_ticket_id(cls, ticket_id):
        row = get_db().execute("SELECT * FROM payments WHERE ticket_id = ?", (ticket_id,)).fetchone()
        return cls._from_row(row)

    @classmethod
    def create(cls, ticket_id, amount):
        db = get_db()
        cur = db.execute(
            "INSERT INTO payments (ticket_id, amount, method, status) VALUES (?, ?, 'card', 'pending')",
            (ticket_id, amount),
        )
        db.commit()
        return cls.get(cur.lastrowid)

    def process_payment(self, method="card"):
        """Simulated payment processing (no real payment gateway wired up)."""
        self.method = method
        self.status = "paid"
        self.paid_at = datetime.utcnow()
        db = get_db()
        db.execute("UPDATE payments SET method=?, status='paid', paid_at=? WHERE id=?",
                    (method, _now(), self.id))
        db.commit()
        ticket = self.ticket
        if ticket:
            ticket.set_status("confirmed")
        return True

    def __repr__(self):
        return f"<Payment #{self.id} {self.status}>"


# ---------------------------------------------------------------------------
# Notification  (replaces notification.py)
# ---------------------------------------------------------------------------

class Notification:
    def __init__(self, id, user_id, message, is_read, created_at):
        self.id = id
        self.user_id = user_id
        self.message = message
        self.is_read = bool(is_read)
        self.created_at = _parse_dt(created_at)

    @staticmethod
    def _from_row(row):
        if row is None:
            return None
        return Notification(row["id"], row["user_id"], row["message"], row["is_read"], row["created_at"])

    @classmethod
    def create(cls, user_id, message):
        db = get_db()
        cur = db.execute(
            "INSERT INTO notifications (user_id, message, is_read, created_at) VALUES (?, ?, 0, ?)",
            (user_id, message, _now()),
        )
        db.commit()
        return cls.get(cur.lastrowid)

    @classmethod
    def get(cls, notification_id):
        row = get_db().execute("SELECT * FROM notifications WHERE id = ?", (notification_id,)).fetchone()
        return cls._from_row(row)

    @classmethod
    def for_user(cls, user_id):
        rows = get_db().execute(
            "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
        ).fetchall()
        return [cls._from_row(r) for r in rows]

    def __repr__(self):
        return f"<Notification to user={self.user_id}>"
