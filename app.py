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


# =========================================================
# DATABASE CONNECTION
# =========================================================

def db():
    if not DATABASE_URL:
        raise Exception("DATABASE_URL environment variable is missing")

    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor
    )


# =========================================================
# DATABASE INITIALIZATION
# =========================================================

def init_db():

    con = db()
    cur = con.cursor()

    # -------------------------
    # USERS
    # -------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        );
    """)

    # -------------------------
    # SHIPMENTS
    # -------------------------

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

    # -------------------------
    # TRACKING EVENTS
    # -------------------------

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

    # -------------------------
    # DEFAULT ADMIN
    # -------------------------

    cur.execute(
        "SELECT 1 FROM users LIMIT 1"
    )

    if not cur.fetchone():

        cur.execute(
            """
            INSERT INTO users(
                username,
                password_hash
            )
            VALUES(%s,%s)
            """,
            (
                "admin",
                generate_password_hash("admin123")
            )
        )

    # -------------------------
    # DEMO SHIPMENT
    # -------------------------

    cur.execute(
        "SELECT 1 FROM shipments LIMIT 1"
    )

    if not cur.fetchone():

        now = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

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

        demo_events = [
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

        for status, location, remark, event_time in demo_events:

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
                    event_time
                )
            )

    con.commit()

    cur.close()
    con.close()


# =========================================================
# LOGIN REQUIRED
# =========================================================

def login_required(f):

    @wraps(f)
    def wrapped(*args, **kwargs):

        if not session.get("admin_id"):
            return redirect(
                url_for("admin_login")
            )

        return f(*args, **kwargs)

    return wrapped


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    return render_template(
        "index.html"
    )


@app.route("/about")
def about():

    return render_template(
        "about.html"
    )


# =========================================================
# TRACK FORM
# =========================================================

@app.route(
    "/track",
    methods=["POST"]
)
def track():

    docket = request.form.get(
        "docket",
        ""
    ).strip()

    return redirect(
        url_for(
            "tracking",
            docket=docket
        )
    )


# =========================================================
# CUSTOMER TRACKING PAGE
# =========================================================

@app.route("/tracking/<docket>")
def tracking(docket):

    con = db()
    cur = con.cursor()

    # -------------------------
    # FIND SHIPMENT
    # -------------------------

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

        # IMPORTANT:
        # OLD -> NEW
        #
        # Booked first
        # Delivered last
        #

        cur.execute(
            """
            SELECT *
            FROM tracking_events
            WHERE shipment_id=%s
            ORDER BY event_time ASC, id ASC
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


# =========================================================
# ADMIN LOGIN
# =========================================================

@app.route(
    "/admin/login",
    methods=["GET", "POST"]
)
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

            session["admin_username"] = (
                user["username"]
            )

            return redirect(
                url_for("admin")
            )

        flash(
            "Invalid username or password."
        )

    return render_template(
        "login.html"
    )


# =========================================================
# LOGOUT
# =========================================================

@app.route("/admin/logout")
def logout():

    session.clear()

    return redirect(
        url_for("home")
    )


# =========================================================
# ADMIN DASHBOARD
# =========================================================

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


# =========================================================
# NEW SHIPMENT
# =========================================================

@app.route(
    "/admin/shipment/new",
    methods=["GET", "POST"]
)
@login_required
def new_shipment():

    # -------------------------
    # GET
    # -------------------------

    if request.method == "GET":

        return render_template(
            "shipment_form.html",
            shipment=None,
            latest_event=None
        )

    # -------------------------
    # POST
    # -------------------------

    data = request.form

    # This is ONLY for internal
    # created_at / updated_at.
    #
    # It will NEVER be used as
    # customer tracking event time.

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # -------------------------
    # MANUAL EVENT DATE/TIME
    # -------------------------

    event_date = data.get(
        "event_date",
        ""
    ).strip()

    event_time = data.get(
        "event_time",
        ""
    ).strip()

    if not event_date:
        event_date = data.get(
            "booking_date",
            ""
        ).strip()

    if not event_time:
        event_time = "10:00"

    manual_event_time = (
        f"{event_date} {event_time}:00"
    )

    con = db()
    cur = con.cursor()

    try:

        # -------------------------
        # CREATE SHIPMENT
        # -------------------------

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
                data.get(
                    "consignor",
                    ""
                ).strip(),
                data.get(
                    "consignee",
                    ""
                ).strip(),
                int(
                    data.get(
                        "packages"
                    ) or 1
                ),
                data.get(
                    "weight",
                    ""
                ).strip(),
                data["status"],
                data.get(
                    "location",
                    ""
                ).strip(),
                data.get(
                    "expected_delivery",
                    ""
                ),
                data.get(
                    "remark",
                    ""
                ).strip(),
                now,
                now
            )
        )

        sid = cur.fetchone()["id"]

        # -------------------------
        # BOOKED EVENT
        #
        # Uses manually entered
        # date/time.
        # -------------------------

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

        # -------------------------
        # IF NEW SHIPMENT STATUS
        # IS NOT BOOKED
        # -------------------------

        current_status = data["status"]

        current_location = data.get(
            "location",
            ""
        ).strip()

        current_remark = data.get(
            "remark",
            ""
        ).strip()

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


# =========================================================
# EDIT SHIPMENT
# =========================================================

@app.route(
    "/admin/shipment/<int:sid>/edit",
    methods=["GET", "POST"]
)
@login_required
def edit_shipment(sid):

    con = db()
    cur = con.cursor()

    # -------------------------
    # GET SHIPMENT
    # -------------------------

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

    # =====================================================
    # GET
    # =====================================================

    if request.method == "GET":

        # Get latest event for form
        # default date/time.

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

    # =====================================================
    # POST
    # =====================================================

    data = request.form

    # Internal update time ONLY.
    #
    # This is NOT used for tracking history.

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

    # -------------------------
    # MANUAL EVENT DATE/TIME
    # -------------------------

    event_date = data.get(
        "event_date",
        ""
    ).strip()

    event_time = data.get(
        "event_time",
        ""
    ).strip()

    if not event_date:

        event_date = data.get(
            "booking_date",
            ""
        ).strip()

    if not event_time:

        event_time = "10:00"

    manual_event_time = (
        f"{event_date} {event_time}:00"
    )

    # =====================================================
    # UPDATE SHIPMENT MASTER DATA
    # =====================================================

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
            data.get(
                "consignor",
                ""
            ).strip(),
            data.get(
                "consignee",
                ""
            ).strip(),
            int(
                data.get(
                    "packages"
                ) or 1
            ),
            data.get(
                "weight",
                ""
            ).strip(),
            status,
            location,
            data.get(
                "expected_delivery",
                ""
            ),
            remark,
            now,
            sid
        )
    )

    # =====================================================
    # FIND ORIGINAL BOOKED EVENT
    # =====================================================

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

    booked_event = cur.fetchone()

    # =====================================================
    # CLEAN DUPLICATE BOOKED EVENTS
    #
    # Keep the oldest/original Booked event.
    # =====================================================

    if booked_event:

        cur.execute(
            """
            DELETE FROM tracking_events
            WHERE shipment_id=%s
              AND status='Booked'
              AND id<>%s
            """,
            (
                sid,
                booked_event["id"]
            )
        )

    # =====================================================
    # IMPORTANT BOOKED RULE
    #
    # If current status is BOOKED:
    #
    # Event Date + Event Time
    # are allowed to update Booked.
    #
    # If current status is anything else:
    #
    # DO NOT TOUCH BOOKED.
    # =====================================================

    if status == "Booked":

        if booked_event:

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
                    booked_event["id"]
                )
            )

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
                    "Booked",
                    data["source"].strip(),
                    "Shipment booked.",
                    manual_event_time
                )
            )

    # =====================================================
    # NON-BOOKED STATUS
    # =====================================================

    else:

        # ---------------------------------------------
        # Find latest event with current status.
        # ---------------------------------------------

        cur.execute(
            """
            SELECT *
            FROM tracking_events
            WHERE shipment_id=%s
              AND status=%s
            ORDER BY event_time DESC, id DESC
            LIMIT 1
            """,
            (
                sid,
                status
            )
        )

        same_status_event = cur.fetchone()

        # ---------------------------------------------
        # STATUS CHANGED
        #
        # Create a NEW event using manual date/time.
        # ---------------------------------------------

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

        # ---------------------------------------------
        # STATUS DID NOT CHANGE
        #
        # Update existing latest event.
        # Do NOT create duplicate.
        # ---------------------------------------------

        elif same_status_event:

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
                    same_status_event["id"]
                )
            )

        # ---------------------------------------------
        # No existing event for this status
        # ---------------------------------------------

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

    # =====================================================
    # SAVE
    # =====================================================

    con.commit()

    cur.close()
    con.close()

    flash(
        "Shipment updated."
    )

    return redirect(
        url_for("admin")
    )


# =========================================================
# DELETE SHIPMENT
# =========================================================

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

    flash(
        "Shipment deleted."
    )

    return redirect(
        url_for("admin")
    )


# =========================================================
# API TRACK
# =========================================================

@app.route(
    "/api/track/<docket>"
)
def api_track(docket):

    con = db()
    cur = con.cursor()

    # -------------------------
    # SHIPMENT
    # -------------------------

    cur.execute(
        """
        SELECT *
        FROM shipments
        WHERE lower(docket)=lower(%s)
        """,
        (docket,)
    )

    shipment = cur.fetchone()

    if not shipment:

        cur.close()
        con.close()

        return jsonify(
            {
                "found": False
            }
        ), 404

    # -------------------------
    # HISTORY
    # OLD -> NEW
    # -------------------------

    cur.execute(
        """
        SELECT
            id,
            status,
            location,
            remark,
            event_time
        FROM tracking_events
        WHERE shipment_id=%s
        ORDER BY event_time ASC, id ASC
        """,
        (shipment["id"],)
    )

    events = cur.fetchall()

    cur.close()
    con.close()

    return jsonify(
        {
            "found": True,
            "shipment": dict(shipment),
            "history": [
                dict(event)
                for event in events
            ]
        }
    )


# =========================================================
# START
# =========================================================

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
