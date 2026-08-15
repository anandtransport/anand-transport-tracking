from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime
import os
import psycopg2
from psycopg2.extras import RealDictCursor


app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "CHANGE_THIS_SECRET_KEY_IN_PRODUCTION"
)

DATABASE_URL = os.environ.get("DATABASE_URL")


# =========================
# DATABASE CONNECTION
# =========================

def db():
    if not DATABASE_URL:
        raise Exception("DATABASE_URL environment variable is missing")

    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor
    )


# =========================
# DATABASE INITIALIZATION
# =========================

def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        );
    """)

    cur.execute("""
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
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tracking_events(
            id SERIAL PRIMARY KEY,
            shipment_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            location TEXT,
            remark TEXT,
            event_time TEXT NOT NULL,
            FOREIGN KEY(shipment_id)
                REFERENCES shipments(id)
                ON DELETE CASCADE
        );
    """)

    # Create admin user if no user exists
    cur.execute("SELECT 1 FROM users LIMIT 1")

    if not cur.fetchone():
        cur.execute(
            """
            INSERT INTO users(username, password_hash)
            VALUES(%s, %s)
            """,
            (
                "admin",
                generate_password_hash("admin123")
            )
        )

    # Create demo shipment only if database is empty
    cur.execute("SELECT 1 FROM shipments LIMIT 1")

    if not cur.fetchone():

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cur.execute(
            """
            INSERT INTO shipments
            (
                docket,
                booking_date,
                source,
                destination,
                consignor,
                consignee,
                packages,
                weight,
                status,
                location,
                expected_delivery,
                remark,
                created_at,
                updated_at
            )
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (
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
            )
        )

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
            cur.execute(
                """
                INSERT INTO tracking_events
                (
                    shipment_id,
                    status,
                    location,
                    remark,
                    event_time
                )
                VALUES(%s,%s,%s,%s,%s)
                """,
                (sid, st, loc, remark, tm)
            )

    con.commit()
    cur.close()
    con.close()


# =========================
# LOGIN
# =========================

def login_required(f):

    @wraps(f)
    def wrapped(*args, **kwargs):

        if not session.get("admin_id"):
            return redirect(url_for("admin_login"))

        return f(*args, **kwargs)

    return wrapped


# =========================
# HOME
# =========================

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/about")
def about():
    return render_template("about.html")


# =========================
# TRACK
# =========================

@app.route("/track", methods=["POST"])
def track():

    docket = request.form.get("docket", "").strip()

    return redirect(
        url_for("tracking", docket=docket)
    )


@app.route("/tracking/<docket>")
def tracking(docket):

    con = db()
    cur = con.cursor()

    cur.execute(
        """
        SELECT *
        FROM shipments
        WHERE lower(docket)=lower(%s)
        """,
        (docket,)
    )

    shipment = cur.fetchone()

    events = []

    if shipment:

        cur.execute(
            """
            SELECT *
            FROM tracking_events
            WHERE shipment_id=%s
            ORDER BY event_time DESC, id DESC
            """,
            (shipment["id"],)
        )

        events = cur.fetchall()

    cur.close()
    con.close()

    return render_template(
        "tracking.html",
        shipment=shipment,
        events=events,
        docket=docket
    )


# =========================
# ADMIN LOGIN
# =========================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        con = db()
        cur = con.cursor()

        cur.execute(
            """
            SELECT *
            FROM users
            WHERE username=%s
            """,
            (username,)
        )

        user = cur.fetchone()

        cur.close()
        con.close()

        if user and check_password_hash(
            user["password_hash"],
            password
        ):

            session["admin_id"] = user["id"]
            session["admin_username"] = user["username"]

            return redirect(
                url_for("admin")
            )

        flash("Invalid username or password.")

    return render_template("login.html")


# =========================
# LOGOUT
# =========================

@app.route("/admin/logout")
def logout():

    session.clear()

    return redirect(
        url_for("home")
    )


# =========================
# ADMIN
# =========================

@app.route("/admin")
@login_required
def admin():

    con = db()
    cur = con.cursor()

    cur.execute(
        """
        SELECT *
        FROM shipments
        ORDER BY updated_at DESC
        """
    )

    shipments = cur.fetchall()

    cur.close()
    con.close()

    return render_template(
        "admin.html",
        shipments=shipments
    )


# =========================
# NEW SHIPMENT
# =========================

@app.route(
    "/admin/shipment/new",
    methods=["GET", "POST"]
)
@login_required
def new_shipment():

    if request.method == "POST":

        data = request.form

        now = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        # -----------------------------------------
        # MANUAL EVENT DATE + TIME
        # -----------------------------------------

        event_date = data.get("event_date", "").strip()
        event_time = data.get("event_time", "").strip()

        if not event_date:
            event_date = data["booking_date"]

        if not event_time:
            event_time = "10:00"

        manual_event_time = f"{event_date} {event_time}:00"

        con = db()
        cur = con.cursor()

        try:

            cur.execute(
                """
                INSERT INTO shipments
                (
                    docket,
                    booking_date,
                    source,
                    destination,
                    consignor,
                    consignee,
                    packages,
                    weight,
                    status,
                    location,
                    expected_delivery,
                    remark,
                    created_at,
                    updated_at
                )
                VALUES
                (
                    %s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s
                )
                RETURNING id
                """,
                (
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
                )
            )

            sid = cur.fetchone()["id"]

            # -----------------------------------------
            # FIRST BOOKED EVENT
            # Uses MANUALLY ENTERED date/time
            # -----------------------------------------

            booking_event_time = manual_event_time

            cur.execute(
                """
                INSERT INTO tracking_events
                (
                    shipment_id,
                    status,
                    location,
                    remark,
                    event_time
                )
                VALUES(%s,%s,%s,%s,%s)
                """,
                (
                    sid,
                    "Booked",
                    data["source"].strip(),
                    "Shipment booked.",
                    booking_event_time
                )
            )

            current_status = data["status"]

            current_location = data.get(
                "location",
                ""
            ).strip()

            current_remark = data.get(
                "remark",
                ""
            ).strip()

            # -----------------------------------------
            # IF INITIAL STATUS IS NOT BOOKED
            # CREATE THAT EVENT USING MANUAL DATE/TIME
            # -----------------------------------------

            if current_status != "Booked":

                cur.execute(
                    """
                    INSERT INTO tracking_events
                    (
                        shipment_id,
                        status,
                        location,
                        remark,
                        event_time
                    )
                    VALUES(%s,%s,%s,%s,%s)
                    """,
                    (
                        sid,
                        current_status,
                        current_location,
                        current_remark,
                        manual_event_time
                    )
                )

            con.commit()

            flash(
                "Shipment created successfully."
            )

        except psycopg2.IntegrityError:

            con.rollback()

            flash(
                "Docket number already exists."
            )

        finally:

            cur.close()
            con.close()

        return redirect(
            url_for("admin")
        )

    return render_template(
        "shipment_form.html",
        shipment=None,
        latest_event=None
    )


# =========================
# EDIT SHIPMENT
# =========================

@app.route(
    "/admin/shipment/<int:sid>/edit",
    methods=["GET", "POST"]
)
@login_required
def edit_shipment(sid):

    con = db()
    cur = con.cursor()

    cur.execute(
        """
        SELECT *
        FROM shipments
        WHERE id=%s
        """,
        (sid,)
    )

    old = cur.fetchone()

    if not old:

        cur.close()
        con.close()

        return "Not found", 404

    # =========================================
    # GET - LOAD LATEST TRACKING EVENT
    # =========================================

    if request.method == "GET":

        cur.execute(
            """
            SELECT *
            FROM tracking_events
            WHERE shipment_id=%s
            ORDER BY event_time DESC, id DESC
            LIMIT 1
            """,
            (sid,)
        )

        latest_event = cur.fetchone()

        cur.close()
        con.close()

        return render_template(
            "shipment_form.html",
            shipment=old,
            latest_event=latest_event
        )

    # =========================================
    # POST
    # =========================================

    data = request.form

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    status = data["status"]

    location = data.get(
        "location",
        ""
    ).strip()

    remark = data.get(
        "remark",
        ""
    ).strip()

    # -----------------------------------------
    # MANUAL EVENT DATE + TIME
    # -----------------------------------------

    event_date = data.get(
        "event_date",
        ""
    ).strip()

    event_time = data.get(
        "event_time",
        ""
    ).strip()

    if not event_date:
        event_date = data["booking_date"]

    if not event_time:
        event_time = "10:00"

    manual_event_time = f"{event_date} {event_time}:00"

    # =========================================
    # UPDATE SHIPMENT
    # =========================================

    cur.execute(
        """
        UPDATE shipments
        SET
            docket=%s,
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
        """,
        (
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
        )
    )

    # =========================================
    # FIND ORIGINAL BOOKED EVENT
    # =========================================

    cur.execute(
        """
        SELECT *
        FROM tracking_events
        WHERE shipment_id=%s
          AND status='Booked'
        ORDER BY event_time ASC, id ASC
        LIMIT 1
        """,
        (sid,)
    )

    first_booked = cur.fetchone()

    # =========================================
    # BOOKED EVENT
    # =========================================

    if first_booked:

        # Update original Booked event
        # with manually entered booking date/time.
        cur.execute(
            """
            UPDATE tracking_events
            SET
                location=%s,
                remark=%s,
                event_time=%s
            WHERE id=%s
            """,
            (
                data["source"].strip(),
                "Shipment booked.",
                manual_event_time,
                first_booked["id"]
            )
        )

        # Remove all duplicate Booked events.
        cur.execute(
            """
            DELETE FROM tracking_events
            WHERE shipment_id=%s
              AND status='Booked'
              AND id<>%s
            """,
            (
                sid,
                first_booked["id"]
            )
        )

    else:

        # If Booked event doesn't exist,
        # create exactly one.
        cur.execute(
            """
            INSERT INTO tracking_events
            (
                shipment_id,
                status,
                location,
                remark,
                event_time
            )
            VALUES(%s,%s,%s,%s,%s)
            """,
            (
                sid,
                "Booked",
                data["source"].strip(),
                "Shipment booked.",
                manual_event_time
            )
        )

    # =========================================
    # GET LATEST NON-BOOKED EVENT
    # =========================================

    cur.execute(
        """
        SELECT *
        FROM tracking_events
        WHERE shipment_id=%s
          AND status<>'Booked'
        ORDER BY event_time DESC, id DESC
        LIMIT 1
        """,
        (sid,)
    )

    latest_non_booked = cur.fetchone()

    # =========================================
    # STATUS IS NOT BOOKED
    # =========================================

    if status != "Booked":

        # -------------------------------------
        # STATUS CHANGED
        # Create NEW event using manual date/time
        # -------------------------------------

        if status != old["status"]:

            cur.execute(
                """
                INSERT INTO tracking_events
                (
                    shipment_id,
                    status,
                    location,
                    remark,
                    event_time
                )
                VALUES(%s,%s,%s,%s,%s)
                """,
                (
                    sid,
                    status,
                    location,
                    remark,
                    manual_event_time
                )
            )

        # -------------------------------------
        # STATUS SAME
        # Update latest event instead of
        # creating duplicate event.
        # -------------------------------------

        elif latest_non_booked:

            cur.execute(
                """
                UPDATE tracking_events
                SET
                    location=%s,
                    remark=%s,
                    event_time=%s
                WHERE id=%s
                """,
                (
                    location,
                    remark,
                    manual_event_time,
                    latest_non_booked["id"]
                )
            )

        # -------------------------------------
        # No non-booked event exists
        # -------------------------------------

        else:

            cur.execute(
                """
                INSERT INTO tracking_events
                (
                    shipment_id,
                    status,
                    location,
                    remark,
                    event_time
                )
                VALUES(%s,%s,%s,%s,%s)
                """,
                (
                    sid,
                    status,
                    location,
                    remark,
                    manual_event_time
                )
            )

    con.commit()

    cur.close()
    con.close()

    flash("Shipment updated.")

    return redirect(
        url_for("admin")
    )


# =========================
# DELETE SHIPMENT
# =========================

@app.route(
    "/admin/shipment/<int:sid>/delete",
    methods=["POST"]
)
@login_required
def delete_shipment(sid):

    con = db()
    cur = con.cursor()

    cur.execute(
        """
        DELETE FROM shipments
        WHERE id=%s
        """,
        (sid,)
    )

    con.commit()

    cur.close()
    con.close()

    flash("Shipment deleted.")

    return redirect(
        url_for("admin")
    )


# =========================
# API TRACK
# =========================

@app.route("/api/track/<docket>")
def api_track(docket):

    con = db()
    cur = con.cursor()

    cur.execute(
        """
        SELECT *
        FROM shipments
        WHERE lower(docket)=lower(%s)
        """,
        (docket,)
    )

    s = cur.fetchone()

    if not s:

        cur.close()
        con.close()

        return jsonify(
            {"found": False}
        ), 404

    cur.execute(
        """
        SELECT
            status,
            location,
            remark,
            event_time
        FROM tracking_events
        WHERE shipment_id=%s
        ORDER BY event_time DESC, id DESC
        """,
        (s["id"],)
    )

    events = cur.fetchall()

    cur.close()
    con.close()

    return jsonify(
        {
            "found": True,
            "shipment": dict(s),
            "history": [
                dict(x)
                for x in events
            ]
        }
    )


# =========================
# START DATABASE
# =========================

init_db()


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        ),
        debug=True
    )
