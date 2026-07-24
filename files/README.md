# RouteBoard — Bus Ticketing Website

A working Flask website built from your original class files (bus, driver,
passenger, route, ticket, payment, notification, GPS device, admin, user).

## What was wrong with the originals

None of the uploaded files actually ran:

- **Syntax errors**: method and class names contained spaces —
  `def manage routes(self, )`, `def share location(self, )`,
  `class GPS device:` — which is invalid Python.
- **Invalid type hints**: `payment.py` had `self.payment id = None` (not a
  legal attribute name) and `uSER.py` annotated a field as `:string` (not a
  real Python type — should be `str`).
- **No bodies**: every method was just `pass`, so even once the syntax was
  fixed, nothing actually happened.
- **No connections between classes**: a `Route` had no notion of a
  timetable, so nothing was ever bookable; `Ticket` and `Payment` didn't
  reference each other; `Driver`/`Bus`/`GPS device` had no link either.
- **`app.py`** only rendered one static template with no routes, forms, or
  models wired up at all.
- **`class1.py` / `class5.py`** were empty placeholders with no fields or
  behavior, so there was nothing to carry forward from them.

## What's here now

- `models.py` — every original class rebuilt with valid names and real
  logic: `Driver.share_location()`, `Driver.send_emergency_alert()`,
  `Route.calculate_fare()`, `Ticket.cancel()`, `Payment.process_payment()`,
  etc. Added a `Trip` model (a bus running a route at a scheduled time),
  since that connective piece didn't exist before and nothing can be booked
  without it.
- `db.py` — SQLite schema and connection handling (stdlib `sqlite3`, no
  extra services to install).
- `app.py` — real routes: browse/search routes, view a route's upcoming
  departures, book a seat, pay (simulated), view/cancel your tickets, a
  driver console (share location, go on/off duty, send an emergency alert),
  and an admin dashboard (add routes, buses, schedule trips).
- `templates/` + `static/` — a full front end themed around a bus
  destination board: a split-flap hero, route "line" cards, and
  boarding-pass style ticket cards.

## Running it

```bash
pip install -r requirements.txt
python app.py
```

Then open `http://127.0.0.1:5000`. A SQLite database (`routeboard.db`) and
some demo data are created automatically on first run.

**Demo logins:**
- Admin: `admin@routeboard.test` / `admin123`
- Driver: `driver@routeboard.test` / `driver123`
- Or register your own passenger/driver account.

## Notes

- Payment is simulated — no real payment gateway is wired up.
- Auth uses Flask's built-in session cookie rather than Flask-Login, so the
  app has zero third-party dependencies beyond Flask itself.
