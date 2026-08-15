from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime
import os

DATABASE_URL = os.environ.get("DATABASE_URL")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "CHANGE_THIS_SECRET_KEY_IN_PRODUCTION")


def db():
    import psycopg
    from psycopg.rows import dict_row

    con = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    return con


def init_db():
    con = db()

    con.execute("""
    CREATE TABLE IF NOT EXISTS users(
      id SERIAL PRIMARY KEY,
      username TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS shipments(
      id SERIAL PRIMARY KEY,
      docket TEXT UNIQUE NOT NULL,
      booking_date TEXT NOT NULL,
      source TEXT NOT NULL,
      destination TEXT NOT NULL,
      consignor TEXT,
      consignee TEXT,
      packages INTEGER DEFAULT 1,
      weight TEXT,
      status TEXT NOT NULL,
      location TEXT,
      expected_delivery TEXT,
      remark TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS tracking_events(
      id SERIAL PRIMARY KEY,
      shipment_id INTEGER NOT NULL,
      status TEXT NOT NULL,
      location TEXT,
      remark TEXT,
      event_time TEXT NOT NULL,
      FOREIGN KEY(shipment_id) REFERENCES shipments(id) ON DELETE CASCADE
    );
    """)

    user = con.execute(
        "SELECT 1 FROM users LIMIT 1"
    ).fetchone()

    if not user:
        con.execute(
            "INSERT INTO users(username,password_hash) VALUES(%s,%s)",
            ("admin", generate_password_hash("admin123"))
        )

    shipment = con.execute(
        "SELECT 1 FROM shipments LIMIT 1"
    ).fetchone()

    if not shipment:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cur = con.execute("""
            INSERT INTO shipments
            (docket,booking_date,source,destination,consignor,consignee,
             packages,weight,status,location,expected_delivery,remark,
             created_at,updated_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (
            "AT100001",
            "2026-08-10",
            "Jaisalmer",
            "Jaipur",
            "ABC Industries",
            "XYZ Traders",
            2,
            "35 kg",
            "In Transit",
            "Jodhpur",
            "2026-08-16",
            "Shipment reached Jodhpur hub.",
            now,
            now
        ))

        sid = cur.fetchone()["id"]

        events = [
            (
                "Booked",
                "Jaisalmer",
                "Shipment booked.",
                "2026-08-10 10:20:00"
            ),
            (
                "Picked Up",
                "Jaisalmer",
                "Shipment picked up.",
                "2026-08-10 14:30:00"
            ),
            (
                "In Transit",
                "Jodhpur",
                "Shipment reached Jodhpur hub.",
                "2026-08-13 08:45:00"
            )
        ]

        for st, loc, remark, tm in events:
            con.execute("""
                INSERT INTO tracking_events
                (shipment_id,status,location,remark,event_time)
                VALUES(%s,%s,%s,%s,%s)
            """, (sid, st, loc, remark, tm))

    con.commit()
    con.close()


def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)

    return wrapped


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/track", methods=["POST"])
def track():
    docket = request.form.get("docket", "").strip()
    return redirect(url_for("tracking", docket=docket))


@app.route("/tracking/<docket>")
def tracking(docket):
    con = db()

    shipment = con.execute(
        "SELECT * FROM shipments WHERE lower(docket)=lower(%s)",
        (docket,)
    ).fetchone()

    events = []

    if shipment:
        events = con.execute("""
            SELECT *
            FROM tracking_events
            WHERE shipment_id=%s
            ORDER BY event_time DESC
        """, (shipment["id"],)).fetchall()

    con.close()

    return render_template(
        "tracking.html",
        shipment=shipment,
        events=events,
        docket=docket
    )


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        con = db()

        user = con.execute(
            "SELECT * FROM users WHERE username=%s",
            (username,)
        ).fetchone()

        con.close()

        if user and check_password_hash(
            user["password_hash"],
            password
        ):
            session["admin_id"] = user["id"]
            session["admin_username"] = user["username"]

            return redirect(url_for("admin"))

        flash("Invalid username or password.")

    return render_template("login.html")


@app.route("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/admin")
@login_required
def admin():
    con = db()

    shipments = con.execute(
        "SELECT * FROM shipments ORDER BY updated_at DESC"
    ).fetchall()

    con.close()

    return render_template(
        "admin.html",
        shipments=shipments
    )


@app.route("/admin/shipment/new", methods=["GET", "POST"])
@login_required
def new_shipment():

    if request.method == "POST":

        data = request.form

        now = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        con = db()

        try:

            cur = con.execute("""
                INSERT INTO shipments
                (docket,booking_date,source,destination,consignor,
                 consignee,packages,weight,status,location,
                 expected_delivery,remark,created_at,updated_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
            """, (
                data["docket"].strip(),
                data["booking_date"],
                data["source"].strip(),
                data["destination"].strip(),
                data.get("consignor", "").strip(),
                data.get("consignee", "").strip(),
                int(data.get("packages") or 1),
                data.get("weight", "").strip(),
                data["status"],
                data.get("location", "").strip(),
                data.get("expected_delivery", ""),
                data.get("remark", "").strip(),
                now,
                now
            ))

            sid = cur.fetchone()["id"]

            booking_event_time = (
                f"{data['booking_date']} 10:00:00"
            )

            con.execute("""
                INSERT INTO tracking_events
                (shipment_id,status,location,remark,event_time)
                VALUES(%s,%s,%s,%s,%s)
            """, (
                sid,
                "Booked",
                data["source"].strip(),
                "Shipment booked.",
                booking_event_time
            ))

            current_status = data["status"]
            current_location = data.get(
                "location", ""
            ).strip()
            current_remark = data.get(
                "remark", ""
            ).strip()

            if (
                current_status != "Booked"
                or current_location.lower()
                != data["source"].strip().lower()
                or current_remark
            ):
                con.execute("""
                    INSERT INTO tracking_events
                    (shipment_id,status,location,remark,event_time)
                    VALUES(%s,%s,%s,%s,%s)
                """, (
                    sid,
                    current_status,
                    current_location,
                    current_remark,
                    now
                ))

            con.commit()

            flash("Shipment created successfully.")

        except Exception:
            con.rollback()
            flash("Docket number already exists or another error occurred.")

        finally:
            con.close()

        return redirect(url_for("admin"))

    return render_template(
        "shipment_form.html",
        shipment=None
    )


@app.route("/admin/shipment/<int:sid>/edit", methods=["GET", "POST"])
@login_required
def edit_shipment(sid):

    con = db()

    old = con.execute(
        "SELECT * FROM shipments WHERE id=%s",
        (sid,)
    ).fetchone()

    if not old:
        con.close()
        return "Not found", 404

    if request.method == "POST":

        data = request.form

        now = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        status = data["status"]
        location = data.get("location", "").strip()
        remark = data.get("remark", "").strip()

        con.execute("""
            UPDATE shipments
            SET docket=%s,
                booking_date=%s,
                source=%s,
                destination=%s,
                consignor=%s,
                consignee=%s,
                packages=%s,
                weight=%s,
                status=%s,
                location=%s,
                expected_delivery=%s,
                remark=%s,
                updated_at=%s
            WHERE id=%s
        """, (
            data["docket"].strip(),
            data["booking_date"],
            data["source"].strip(),
            data["destination"].strip(),
            data.get("consignor", "").strip(),
            data.get("consignee", "").strip(),
            int(data.get("packages") or 1),
            data.get("weight", "").strip(),
            status,
            location,
            data.get("expected_delivery", ""),
            remark,
            now,
            sid
        ))

        first_event = con.execute("""
            SELECT *
            FROM tracking_events
            WHERE shipment_id=%s
            ORDER BY event_time ASC, id ASC
            LIMIT 1
        """, (sid,)).fetchone()

        if first_event and first_event["status"] == "Booked":

            booking_event_time = (
                f"{data['booking_date']} 10:00:00"
            )

            if (
                first_event["location"]
                != data["source"].strip()
                or first_event["event_time"]
                != booking_event_time
            ):
                con.execute("""
                    UPDATE tracking_events
                    SET location=%s,
                        remark=%s,
                        event_time=%s
                    WHERE id=%s
                """, (
                    data["source"].strip(),
                    "Shipment booked.",
                    booking_event_time,
                    first_event["id"]
                ))

        if (
            status != old["status"]
            or location != old["location"]
            or remark != old["remark"]
        ):

            con.execute("""
                INSERT INTO tracking_events
                (shipment_id,status,location,remark,event_time)
                VALUES(%s,%s,%s,%s,%s)
            """, (
                sid,
                status,
                location,
                remark,
                now
            ))

        con.commit()
        con.close()

        flash("Shipment updated.")

        return redirect(url_for("admin"))

    con.close()

    return render_template(
        "shipment_form.html",
        shipment=old
    )


@app.route("/admin/shipment/<int:sid>/delete", methods=["POST"])
@login_required
def delete_shipment(sid):

    con = db()

    con.execute(
        "DELETE FROM tracking_events WHERE shipment_id=%s",
        (sid,)
    )

    con.execute(
        "DELETE FROM shipments WHERE id=%s",
        (sid,)
    )

    con.commit()
    con.close()

    flash("Shipment deleted.")

    return redirect(url_for("admin"))


@app.route("/api/track/<docket>")
def api_track(docket):

    con = db()

    s = con.execute(
        "SELECT * FROM shipments WHERE lower(docket)=lower(%s)",
        (docket,)
    ).fetchone()

    if not s:
        con.close()
        return jsonify({"found": False}), 404

    events = con.execute("""
        SELECT status,location,remark,event_time
        FROM tracking_events
        WHERE shipment_id=%s
        ORDER BY event_time DESC
    """, (s["id"],)).fetchall()

    con.close()

    return jsonify({
        "found": True,
        "shipment": dict(s),
        "history": [dict(x) for x in events]
    })


init_db()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=True
    )
