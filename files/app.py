#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
RouteBoard — a small bus ticketing website.

Rebuilt from a set of broken stub files (see models.py docstring for the
full list of what was fixed). This app.py replaces the original app.py,
which only rendered a single static "home.html" with no routes, no models,
and no forms wired up.

Auth uses Flask's built-in session (cookie) rather than Flask-Login, since
the environment this was built in has no internet access to install extra
packages — everything here runs on Flask + Werkzeug + the Python standard
library only.
"""

import random
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, redirect, url_for, request, flash, jsonify,
    session, g,
)

from db import get_db, close_db, init_db
from models import (
    User, Driver, Bus, Route, Trip, Ticket, Payment, Notification,
    ROLE_ADMIN, ROLE_DRIVER, ROLE_PASSENGER,
)

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-secret-key-change-me"

app.teardown_appcontext(close_db)


# ---------------------------------------------------------------------------
# Lightweight session-based auth helpers
# ---------------------------------------------------------------------------

@app.before_request
def load_logged_in_user():
    user_id = session.get("user_id")
    g.user = User.get(user_id) if user_id else None


@app.context_processor
def inject_current_user():
    class _Anon:
        is_authenticated = False
        is_admin = False
        is_driver = False
        name = ""
    return {"current_user": g.user if g.user else _Anon()}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Please sign in to continue.", "info")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    routes = Route.all()[:6]
    return render_template("home.html", routes=routes)


@app.route("/routes")
def routes_list():
    q_origin = request.args.get("origin", "").strip()
    q_dest = request.args.get("destination", "").strip()
    routes = Route.search(origin=q_origin, destination=q_dest)
    return render_template("routes.html", routes=routes, q_origin=q_origin, q_dest=q_dest)


@app.route("/routes/<int:route_id>")
def route_detail(route_id):
    route = Route.get(route_id)
    if route is None:
        return render_template("404.html"), 404
    trips = Trip.upcoming_for_route(route_id)
    return render_template("route_detail.html", route=route, trips=trips)


@app.route("/track/<int:bus_id>")
def track_bus(bus_id):
    bus = Bus.get(bus_id)
    if bus is None:
        return render_template("404.html"), 404
    trip = Trip.latest_for_bus(bus_id)
    return render_template("track_bus.html", bus=bus, trip=trip)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", ROLE_PASSENGER)

        if role not in (ROLE_PASSENGER, ROLE_DRIVER):
            role = ROLE_PASSENGER

        if not name or not email or not password:
            flash("All fields are required.", "error")
            return render_template("register.html")

        if User.get_by_email(email):
            flash("An account with that email already exists.", "error")
            return render_template("register.html")

        user = User.create(name=name, email=email, role=role)
        user.set_password(password)
        user.save()

        if role == ROLE_DRIVER:
            license_no = request.form.get("license_no", "").strip() or f"LIC-{user.id:04d}"
            Driver.create(user_id=user.id, license_no=license_no)

        flash("Account created. Please sign in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.get_by_email(email)

        if user and user.check_password(password):
            session["user_id"] = user.id
            flash(f"Welcome back, {user.name}.", "success")
            if user.is_admin:
                return redirect(url_for("admin_dashboard"))
            if user.is_driver:
                return redirect(url_for("driver_dashboard"))
            return redirect(url_for("home"))

        flash("Incorrect email or password.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Signed out.", "info")
    return redirect(url_for("home"))


# ---------------------------------------------------------------------------
# Booking & payment (passenger)
# ---------------------------------------------------------------------------

@app.route("/book/<int:trip_id>", methods=["GET", "POST"])
@login_required
def book_trip(trip_id):
    trip = Trip.get(trip_id)
    if trip is None:
        return render_template("404.html"), 404

    if request.method == "POST":
        if trip.seats_available <= 0:
            flash("Sorry, this trip is fully booked.", "error")
            return redirect(url_for("route_detail", route_id=trip.route_id))

        seat_no = trip.seats_booked + 1
        fare = trip.route.calculate_fare()

        ticket = Ticket.create(trip_id=trip.id, passenger_id=g.user.id,
                                seat_no=seat_no, fare=fare, status="pending")
        trip.increment_seats()

        return redirect(url_for("pay_ticket", ticket_id=ticket.id))

    return render_template("book_ticket.html", trip=trip)


@app.route("/pay/<int:ticket_id>", methods=["GET", "POST"])
@login_required
def pay_ticket(ticket_id):
    ticket = Ticket.get(ticket_id)
    if ticket is None:
        return render_template("404.html"), 404
    if ticket.passenger_id != g.user.id:
        flash("That ticket doesn't belong to your account.", "error")
        return redirect(url_for("my_tickets"))

    payment = ticket.payment or Payment.create(ticket_id=ticket.id, amount=ticket.fare)

    if request.method == "POST":
        method = request.form.get("method", "card")
        payment.process_payment(method=method)
        Notification.create(
            g.user.id, f"Payment confirmed for ticket #{ticket.id}. Seat {ticket.seat_no}.",
        )
        flash("Payment successful. Your seat is confirmed.", "success")
        return redirect(url_for("my_tickets"))

    return render_template("pay_ticket.html", ticket=ticket, payment=payment)


@app.route("/tickets")
@login_required
def my_tickets():
    tickets = Ticket.for_passenger(g.user.id)
    return render_template("my_tickets.html", tickets=tickets)


@app.route("/tickets/<int:ticket_id>/cancel", methods=["POST"])
@login_required
def cancel_ticket(ticket_id):
    ticket = Ticket.get(ticket_id)
    if ticket is None:
        return render_template("404.html"), 404
    if ticket.passenger_id != g.user.id:
        flash("That ticket doesn't belong to your account.", "error")
        return redirect(url_for("my_tickets"))

    ticket.cancel()
    flash(f"Ticket #{ticket.id} cancelled.", "info")
    return redirect(url_for("my_tickets"))


# ---------------------------------------------------------------------------
# Driver dashboard
# ---------------------------------------------------------------------------

@app.route("/driver", methods=["GET", "POST"])
@login_required
def driver_dashboard():
    if not g.user.is_driver:
        flash("Driver access only.", "error")
        return redirect(url_for("home"))

    driver = g.user.driver_profile

    if request.method == "POST":
        action = request.form.get("action")
        if action == "update_location":
            lat = float(request.form.get("lat", 0))
            lng = float(request.form.get("lng", 0))
            driver.share_location(lat, lng)
            flash("Location updated.", "success")
        elif action == "toggle_duty":
            driver.on_duty = not driver.on_duty
            driver.save()
            flash("Duty status updated.", "info")
        elif action == "emergency":
            driver.send_emergency_alert()
            flash("Emergency alert sent to admins.", "error")
        return redirect(url_for("driver_dashboard"))

    trips = Trip.upcoming_for_bus(driver.bus.id) if driver and driver.bus else []
    return render_template("driver_dashboard.html", driver=driver, trips=trips)


# ---------------------------------------------------------------------------
# Admin dashboard
# ---------------------------------------------------------------------------

@app.route("/admin", methods=["GET"])
@login_required
def admin_dashboard():
    if not g.user.is_admin:
        flash("Admin access only.", "error")
        return redirect(url_for("home"))

    stats = {
        "users": User.count(),
        "buses": Bus.count(),
        "routes": Route.count(),
        "tickets": Ticket.count_confirmed(),
    }
    buses = Bus.all()
    routes = Route.all()
    drivers = Driver.all()
    return render_template("admin_dashboard.html", stats=stats, buses=buses,
                            routes=routes, drivers=drivers)


@app.route("/admin/routes", methods=["POST"])
@login_required
def admin_add_route():
    if not g.user.is_admin:
        flash("Admin access only.", "error")
        return redirect(url_for("home"))

    code = request.form.get("code", "").strip().upper()
    name = request.form.get("name", "").strip()
    origin = request.form.get("origin", "").strip()
    destination = request.form.get("destination", "").strip()
    distance_km = float(request.form.get("distance_km") or 0)
    duration_min = int(request.form.get("duration_min") or 0)
    base_fare = float(request.form.get("base_fare") or 0)
    color = random.choice(["#2F7A6F", "#F2A93B", "#C1443C", "#6C5CE7", "#1B7FB8"])

    Route.create(code=code, name=name, origin=origin, destination=destination,
                 distance_km=distance_km, duration_min=duration_min,
                 base_fare=base_fare, color=color)
    flash(f"Route {code} added.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/buses", methods=["POST"])
@login_required
def admin_add_bus():
    if not g.user.is_admin:
        flash("Admin access only.", "error")
        return redirect(url_for("home"))

    bus_number = request.form.get("bus_number", "").strip().upper()
    capacity = int(request.form.get("capacity") or 40)
    driver_id = request.form.get("driver_id") or None

    Bus.create(bus_number=bus_number, capacity=capacity, driver_id=driver_id)
    flash(f"Bus {bus_number} added.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/trips", methods=["POST"])
@login_required
def admin_add_trip():
    if not g.user.is_admin:
        flash("Admin access only.", "error")
        return redirect(url_for("home"))

    route_id = int(request.form.get("route_id"))
    bus_id = int(request.form.get("bus_id"))
    departure_time = request.form.get("departure_time")
    dt = datetime.strptime(departure_time, "%Y-%m-%dT%H:%M")

    Trip.create(route_id=route_id, bus_id=bus_id, departure_time=dt)
    flash("Trip scheduled.", "success")
    return redirect(url_for("admin_dashboard"))


# ---------------------------------------------------------------------------
# Small JSON endpoint used by the live tracking page for a simulated position
# ---------------------------------------------------------------------------

@app.route("/api/bus/<int:bus_id>/location")
def bus_location(bus_id):
    bus = Bus.get(bus_id)
    if bus is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "bus_number": bus.bus_number,
        "lat": bus.current_lat,
        "lng": bus.current_lng,
        "updated_at": bus.location_updated_at.isoformat() if bus.location_updated_at else None,
    })


# ---------------------------------------------------------------------------
# Seed data so the site is browsable immediately
# ---------------------------------------------------------------------------

def seed_data():
    with app.app_context():
        if User.count() > 0:
            return

        admin_user = User.create(name="Asha Rai", email="admin@routeboard.test", role=ROLE_ADMIN)
        admin_user.set_password("admin123")
        admin_user.save()

        driver_user = User.create(name="Bikash Thapa", email="driver@routeboard.test", role=ROLE_DRIVER)
        driver_user.set_password("driver123")
        driver_user.save()

        driver = Driver.create(user_id=driver_user.id, license_no="LIC-2201", on_duty=True)

        bus = Bus.create(bus_number="BA-2-KHA-4471", capacity=36, driver_id=driver.id,
                          current_lat=27.7172, current_lng=85.3240)

        routes_data = [
            ("R1", "Ratnapark - Bhaktapur", "Ratnapark", "Bhaktapur", 13.0, 45, 35.0, "#2F7A6F"),
            ("R2", "Kalanki - Koteshwor", "Kalanki", "Koteshwor", 11.5, 40, 30.0, "#F2A93B"),
            ("R3", "Balaju - Satdobato", "Balaju", "Satdobato", 15.0, 50, 40.0, "#C1443C"),
            ("R4", "Gongabu - Lagankhel", "Gongabu", "Lagankhel", 12.0, 42, 32.0, "#1B7FB8"),
        ]
        routes = []
        for code, name, origin, dest, dist, dur, fare, color in routes_data:
            r = Route.create(code=code, name=name, origin=origin, destination=dest,
                              distance_km=dist, duration_min=dur, base_fare=fare, color=color)
            routes.append(r)

        base = datetime.utcnow().replace(minute=0, second=0, microsecond=0) + timedelta(days=1)
        for r in routes:
            for h in (7, 12, 17):
                departure = base.replace(hour=h)
                Trip.create(route_id=r.id, bus_id=bus.id, departure_time=departure)


init_db()
seed_data()


if __name__ == "__main__":
    app.run(debug=True)
