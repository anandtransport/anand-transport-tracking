from flask import (
    Flask, render_template, render_template_string,
    request, redirect, url_for, session, jsonify,
    flash, send_file
)
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import (
    getSampleStyleSheet, ParagraphStyle
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer,
    Table, TableStyle
)
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from decimal import Decimal

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "CHANGE_THIS_SECRET_KEY_IN_PRODUCTION"
)

DATABASE_URL = os.environ.get("DATABASE_URL")

TRANSPORT_NAME = "ANAND TRANSPORT CARRIER"
TRANSPORT_GST = "08AOJPJ9966R1ZO"
TRANSPORT_ADDRESS = (
    "Opposite Mishreelal Girls College, "
    "Dedansar Road, Jaisalmer Raj. - 345001"
)
TRANSPORT_HELPLINE = "+91 7410823003"


# =========================================================
# DATE HELPERS
# =========================================================

def format_date_ddmmyyyy(value):
    if not value:
        return "-"

    text = str(value).strip()

    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(
                text[:10], fmt
            ).strftime("%d-%m-%Y")
        except ValueError:
            pass

    return text


def money_value(value):
    try:
        if value is None or str(value).strip() == "":
            return 0.0

        return float(str(value).replace(",", "").strip())

    except Exception:
        return 0.0


def money_text(value):
    amount = money_value(value)

    if amount == int(amount):
        return f"{int(amount):,}"

    return f"{amount:,.2f}"


# =========================================================
# DATABASE
# =========================================================

def db():

    if not DATABASE_URL:
        raise Exception(
            "DATABASE_URL environment variable is missing"
        )

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
    # EXTRA SHIPMENT COLUMNS
    # -------------------------

    extra_columns = {

        "consignor_address": "TEXT",
        "consignor_contact": "TEXT",

        "consignee_address": "TEXT",
        "consignee_contact": "TEXT",

        "amount": "TEXT",
        "freight_basis": "TEXT",

        "goods_description": "TEXT"
    }

    for column, sql_type in extra_columns.items():

        cur.execute(
            f"""
            ALTER TABLE shipments
            ADD COLUMN IF NOT EXISTS
            {column} {sql_type}
            """
        )

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

    # =====================================================
    # MONEY RECEIPTS
    # =====================================================

    cur.execute("""
        CREATE TABLE IF NOT EXISTS money_receipts(

            id SERIAL PRIMARY KEY,

            receipt_no TEXT UNIQUE NOT NULL,

            shipment_id INTEGER NOT NULL,

            docket TEXT NOT NULL,

            freight TEXT DEFAULT '0',
            handling TEXT DEFAULT '0',
            door_delivery TEXT DEFAULT '0',
            receipt_charge TEXT DEFAULT '0',
            damage TEXT DEFAULT '0',
            additional_charge TEXT DEFAULT '0',

            total TEXT DEFAULT '0',

            note TEXT,

            created_at TEXT NOT NULL,

            FOREIGN KEY(shipment_id)
            REFERENCES shipments(id)
            ON DELETE CASCADE
        );
    """)

    # =====================================================
    # DEFAULT ADMIN
    # =====================================================

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

    # =====================================================
    # DEMO SHIPMENT
    # =====================================================

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
            VALUES(
                %s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s
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

        for event in demo_events:

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
                    event[0],
                    event[1],
                    event[2],
                    event[3]
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
# TRACK
# =========================================================

@app.route("/track", methods=["POST"])
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
# API TRACK
# =========================================================

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

    shipment = cur.fetchone()

    if not shipment:

        cur.close()
        con.close()

        return jsonify(
            {
                "found": False
            }
        ), 404

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
# CHANGE CREDENTIALS
# =========================================================

@app.route(
    "/admin/change-credentials",
    methods=["GET", "POST"]
)
def change_credentials():

    if request.method == "POST":

        current_username = request.form.get(
            "current_username",
            ""
        ).strip()

        current_password = request.form.get(
            "current_password",
            ""
        )

        new_username = request.form.get(
            "new_username",
            ""
        ).strip()

        new_password = request.form.get(
            "new_password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        if not current_username or not new_username or not new_password:

            flash(
                "Username and password are required."
            )

            return redirect(
                url_for("change_credentials")
            )

        if len(new_password) < 6:

            flash(
                "New password must be at least 6 characters long."
            )

            return redirect(
                url_for("change_credentials")
            )

        if new_password != confirm_password:

            flash(
                "New password and confirm password do not match."
            )

            return redirect(
                url_for("change_credentials")
            )

        con = db()
        cur = con.cursor()

        try:

            cur.execute(
                """
                SELECT *
                FROM users
                WHERE username=%s
                """,
                (current_username,)
            )

            user = cur.fetchone()

            if not user or not check_password_hash(
                user["password_hash"],
                current_password
            ):

                flash(
                    "Current password is incorrect."
                )

                return redirect(
                    url_for("change_credentials")
                )

            cur.execute(
                """
                SELECT id
                FROM users
                WHERE username=%s
                AND id<>%s
                """,
                (
                    new_username,
                    user["id"]
                )
            )

            if cur.fetchone():

                flash(
                    "This username is already in use."
                )

                return redirect(
                    url_for("change_credentials")
                )

            cur.execute(
                """
                UPDATE users
                SET
                    username=%s,
                    password_hash=%s
                WHERE id=%s
                """,
                (
                    new_username,
                    generate_password_hash(
                        new_password
                    ),
                    user["id"]
                )
            )

            con.commit()

            session["admin_username"] = new_username

            flash(
                "Admin username and password changed successfully."
            )

            return redirect(
                url_for("admin")
            )

        except Exception:

            con.rollback()

            flash(
                "Unable to change login details."
            )

            return redirect(
                url_for("change_credentials")
            )

        finally:

            cur.close()
            con.close()

    return render_template_string(
        """
        <!doctype html>
        <html>
        <head>
        <meta charset="UTF-8">
        <meta name="viewport"
              content="width=device-width,initial-scale=1">

        <title>Change Admin Login</title>

        <style>
        body{
            font-family:Arial;
            background:#f5f5f5;
            padding:40px 20px;
        }

        .box{
            max-width:500px;
            margin:auto;
            background:white;
            padding:30px;
            border-radius:14px;
            box-shadow:0 5px 20px #0002;
        }

        label{
            display:block;
            margin-top:15px;
            margin-bottom:6px;
            font-weight:bold;
        }

        input{
            width:100%;
            padding:11px;
            box-sizing:border-box;
            border:1px solid #ccc;
            border-radius:7px;
        }

        button{
            margin-top:20px;
            padding:12px 18px;
            background:#b00000;
            color:white;
            border:0;
            border-radius:7px;
            cursor:pointer;
        }

        .back{
            margin-left:10px;
        }
        </style>
        </head>

        <body>

        <div class="box">

        <h2>Change Admin Login</h2>

        <form method="POST">

        <label>Current Username</label>
        <input
            name="current_username"
            value="{{ session.get('admin_username','') }}"
            required
        >

        <label>Current Password</label>
        <input
            type="password"
            name="current_password"
            required
        >

        <label>New Username</label>
        <input
            name="new_username"
            value="{{ session.get('admin_username','') }}"
            required
        >

        <label>New Password</label>
        <input
            type="password"
            name="new_password"
            minlength="6"
            required
        >

        <label>Confirm New Password</label>
        <input
            type="password"
            name="confirm_password"
            minlength="6"
            required
        >

        <button>
            Save New Login Details
        </button>

        <a
            class="back"
            href="{{ url_for('admin') }}"
        >
            Back
        </a>

        </form>

        </div>

        </body>
        </html>
        """
    )


# =========================================================
# GENERATE GR NUMBER
# =========================================================

def generate_gr_no():

    con = db()
    cur = con.cursor()

    prefix = datetime.now().strftime(
        "ATC-%Y%m%d"
    )

    cur.execute(
        """
        SELECT COUNT(*) AS c
        FROM shipments
        WHERE docket LIKE %s
        """,
        (
            prefix + "%",
        )
    )

    count = cur.fetchone()["c"] + 1

    cur.close()
    con.close()

    return f"{prefix}-{count:04d}"


# =========================================================
# PDF HELPERS
# =========================================================

def _pdf_paragraph(text, style):

    import html

    return Paragraph(
        html.escape(
            str(text or "")
        ),
        style
    )


def pdf_header(story, styles):

    title = ParagraphStyle(
        "ATCTitle",
        parent=styles["Title"],
        fontSize=19,
        leading=22,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#b00000"),
        spaceAfter=2
    )

    center = ParagraphStyle(
        "ATCCenter",
        parent=styles["Normal"],
        fontSize=8.2,
        leading=10.5,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#333333")
    )

    logo_text = ParagraphStyle(
        "ATCLogoText",
        parent=styles["Normal"],
        fontSize=16,
        leading=17,
        alignment=TA_CENTER,
        textColor=colors.white
    )

    logo_sub = ParagraphStyle(
        "ATCLogoSub",
        parent=styles["Normal"],
        fontSize=5.2,
        leading=6,
        alignment=TA_CENTER,
        textColor=colors.white
    )

    logo = Table(
        [
            [Paragraph("<b>ATC</b>", logo_text)],
            [Paragraph("TRANSPORT", logo_sub)]
        ],
        colWidths=[58],
        rowHeights=[28, 10]
    )

    logo.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#b00000")),
            ("BOX", (0, 0), (-1, -1), 1.8, colors.HexColor("#f0a900")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1)
        ])
    )

    header = Table(
        [
            [
                logo,
                [
                    Paragraph(TRANSPORT_NAME, title),
                    Paragraph(
                        f"GST ID: {TRANSPORT_GST} | Helpline: {TRANSPORT_HELPLINE}",
                        center
                    ),
                    Paragraph(TRANSPORT_ADDRESS, center)
                ]
            ]
        ],
        colWidths=[70, 454]
    )

    header.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LINEBELOW", (0, 0), (-1, -1), 1.2, colors.HexColor("#f0a900"))
        ])
    )

    story.append(header)
    story.append(Spacer(1, 9))


# =========================================================
# SHIPMENT PDF
# =========================================================

@app.route(
    "/admin/shipment/<int:sid>/pdf"
)
@login_required
def shipment_pdf(sid):

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

    shipment = cur.fetchone()

    cur.close()
    con.close()

    if not shipment:

        return "Shipment not found", 404

    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=28,
        leftMargin=28,
        topMargin=24,
        bottomMargin=30
    )

    styles = getSampleStyleSheet()

    heading = ParagraphStyle(
        "PDFHeading",
        parent=styles["Heading2"],
        fontSize=10.5,
        leading=13,
        textColor=colors.HexColor("#b00000"),
        spaceBefore=4,
        spaceAfter=4
    )

    normal = ParagraphStyle(
        "PDFNormal",
        parent=styles["Normal"],
        fontSize=8.7,
        leading=11
    )

    small = ParagraphStyle(
        "PDFSmall",
        parent=styles["Normal"],
        fontSize=7.8,
        leading=9.5
    )

    right = ParagraphStyle(
        "PDFRight",
        parent=normal,
        alignment=TA_RIGHT
    )

    story = []

    pdf_header(
        story,
        styles
    )

    story.append(
        Paragraph(
            "CONSIGNMENT / GR BOOKING RECEIPT",
            heading
        )
    )

    booking_date = format_date_ddmmyyyy(
        shipment.get("booking_date")
    )

    expected_date = format_date_ddmmyyyy(
        shipment.get("expected_delivery")
    )

    freight_basis = (
        shipment.get("freight_basis")
        or "To Pay"
    )

    # =====================================================
    # AMOUNT RULE
    #
    # To Pay -> amount shown
    # Paid/TBB -> amount hidden
    # =====================================================

    if freight_basis == "To Pay":

        info = [

            [
                _pdf_paragraph(
                    "GR / Consignment No.",
                    normal
                ),

                _pdf_paragraph(
                    shipment["docket"],
                    normal
                ),

                _pdf_paragraph(
                    "Booking Date",
                    normal
                ),

                _pdf_paragraph(
                    booking_date,
                    normal
                )
            ],

            [
                _pdf_paragraph(
                    "Expected Delivery",
                    normal
                ),

                _pdf_paragraph(
                    expected_date,
                    normal
                ),

                _pdf_paragraph(
                    "Status",
                    normal
                ),

                _pdf_paragraph(
                    shipment["status"],
                    normal
                )
            ],

            [
                _pdf_paragraph(
                    "From",
                    normal
                ),

                _pdf_paragraph(
                    shipment["source"],
                    normal
                ),

                _pdf_paragraph(
                    "To",
                    normal
                ),

                _pdf_paragraph(
                    shipment["destination"],
                    normal
                )
            ],

            [
                _pdf_paragraph(
                    "Packages",
                    normal
                ),

                _pdf_paragraph(
                    shipment.get("packages"),
                    normal
                ),

                _pdf_paragraph(
                    "Weight",
                    normal
                ),

                _pdf_paragraph(
                    shipment.get("weight") or "-",
                    normal
                )
            ],

            [
                _pdf_paragraph(
                    "Freight Basis",
                    normal
                ),

                _pdf_paragraph(
                    freight_basis,
                    normal
                ),

                _pdf_paragraph(
                    "Amount",
                    normal
                ),

                _pdf_paragraph(
                    "₹ " + money_text(
                        shipment.get("amount")
                    ),
                    normal
                )
            ]
        ]

    else:

        info = [

            [
                _pdf_paragraph(
                    "GR / Consignment No.",
                    normal
                ),

                _pdf_paragraph(
                    shipment["docket"],
                    normal
                ),

                _pdf_paragraph(
                    "Booking Date",
                    normal
                ),

                _pdf_paragraph(
                    booking_date,
                    normal
                )
            ],

            [
                _pdf_paragraph(
                    "Expected Delivery",
                    normal
                ),

                _pdf_paragraph(
                    expected_date,
                    normal
                ),

                _pdf_paragraph(
                    "Status",
                    normal
                ),

                _pdf_paragraph(
                    shipment["status"],
                    normal
                )
            ],

            [
                _pdf_paragraph(
                    "From",
                    normal
                ),

                _pdf_paragraph(
                    shipment["source"],
                    normal
                ),

                _pdf_paragraph(
                    "To",
                    normal
                ),

                _pdf_paragraph(
                    shipment["destination"],
                    normal
                )
            ],

            [
                _pdf_paragraph(
                    "Packages",
                    normal
                ),

                _pdf_paragraph(
                    shipment.get("packages"),
                    normal
                ),

                _pdf_paragraph(
                    "Weight",
                    normal
                ),

                _pdf_paragraph(
                    shipment.get("weight") or "-",
                    normal
                )
            ],

            [
                _pdf_paragraph(
                    "Freight Basis",
                    normal
                ),

                _pdf_paragraph(
                    freight_basis,
                    normal
                ),

                "",
                ""
            ]
        ]

    t = Table(
        info,
        colWidths=[
            100,
            174,
            92,
            157
        ]
    )

    t.setStyle(
        TableStyle([
            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.5,
                colors.HexColor("#cccccc")
            ),

            (
                "BACKGROUND",
                (0, 0),
                (0, -1),
                colors.HexColor("#f7f7f7")
            ),

            (
                "BACKGROUND",
                (2, 0),
                (2, -1),
                colors.HexColor("#f7f7f7")
            ),

            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "TOP"
            ),

            (
                "LEFTPADDING",
                (0, 0),
                (-1, -1),
                5
            ),

            (
                "RIGHTPADDING",
                (0, 0),
                (-1, -1),
                5
            ),

            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                5
            ),

            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                5
            )
        ])
    )

    story.append(t)

    story.append(
        Spacer(1, 7)
    )

    # =====================================================
    # CONSIGNOR / CONSIGNEE
    # =====================================================

    party = [

        [
            Paragraph(
                "CONSIGNOR",
                heading
            ),

            Paragraph(
                "CONSIGNEE",
                heading
            )
        ],

        [
            _pdf_paragraph(
                "Name: " +
                str(
                    shipment.get("consignor")
                    or "-"
                ),
                normal
            ),

            _pdf_paragraph(
                "Name: " +
                str(
                    shipment.get("consignee")
                    or "-"
                ),
                normal
            )
        ],

        [
            _pdf_paragraph(
                "Address: " +
                str(
                    shipment.get(
                        "consignor_address"
                    ) or "-"
                ),
                small
            ),

            _pdf_paragraph(
                "Address: " +
                str(
                    shipment.get(
                        "consignee_address"
                    ) or "-"
                ),
                small
            )
        ],

        [
            _pdf_paragraph(
                "Contact: " +
                str(
                    shipment.get(
                        "consignor_contact"
                    ) or "-"
                ),
                normal
            ),

            _pdf_paragraph(
                "Contact: " +
                str(
                    shipment.get(
                        "consignee_contact"
                    ) or "-"
                ),
                normal
            )
        ]
    ]

    pt = Table(
        party,
        colWidths=[
            262,
            262
        ]
    )

    pt.setStyle(
        TableStyle([
            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.5,
                colors.HexColor("#cccccc")
            ),

            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.HexColor("#f7f7f7")
            ),

            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "TOP"
            ),

            (
                "LEFTPADDING",
                (0, 0),
                (-1, -1),
                6
            ),

            (
                "RIGHTPADDING",
                (0, 0),
                (-1, -1),
                6
            ),

            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                5
            ),

            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                5
            )
        ])
    )

    story.append(pt)

    story.append(
        Spacer(1, 7)
    )

    # =====================================================
    # GOODS
    # =====================================================

    goods = (
        shipment.get("goods_description")
        or "-"
    )

    goods_table = Table(
        [
            [
                Paragraph(
                    "GOODS DESCRIPTION",
                    heading
                )
            ],

            [
                _pdf_paragraph(
                    goods,
                    normal
                )
            ]
        ],
        colWidths=[524]
    )

    goods_table.setStyle(
        TableStyle([
            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.5,
                colors.HexColor("#cccccc")
            ),

            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.HexColor("#f7f7f7")
            ),

            (
                "LEFTPADDING",
                (0, 0),
                (-1, -1),
                6
            ),

            (
                "RIGHTPADDING",
                (0, 0),
                (-1, -1),
                6
            ),

            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                4
            ),

            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                4
            )
        ])
    )

    story.append(goods_table)

    story.append(
        Spacer(1, 8)
    )

    # =====================================================
    # REMARKS
    # =====================================================

    story.append(
        Paragraph(
            "REMARKS",
            heading
        )
    )

    story.append(
        _pdf_paragraph(
            shipment.get("remark") or "-",
            normal
        )
    )

    story.append(Spacer(1, 8))

    terms_title = ParagraphStyle(
        "TermsTitle",
        parent=heading,
        fontSize=8.5,
        leading=10,
        spaceBefore=2,
        spaceAfter=3
    )

    terms_box = Table(
        [[Paragraph("TERMS & CONDITIONS", terms_title)],
         [_pdf_paragraph(
             "1. Goods are accepted subject to applicable transport rules. "
             "2. Consignor is responsible for correct packing and declaration. "
             "3. Delivery is subject to route, service availability and required documents. "
             "4. Shortage/damage must be reported at the time of delivery.",
             small
         )]],
        colWidths=[524]
    )

    terms_box.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f7f7f7")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4)
    ]))

    story.append(terms_box)
    story.append(Spacer(1, 12))

    story.append(
        Paragraph(
            "For ANAND TRANSPORT CARRIER",
            right
        )
    )

    doc.build(story)

    buffer.seek(0)

    filename = (
        f"{shipment['docket']}_GR.pdf"
    )

    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf"
    )


# =========================================================
# ADMIN DASHBOARD
# =========================================================

ADMIN_DASHBOARD_HTML = r'''
<!doctype html>

<html lang="en">

<head>

<meta charset="utf-8">

<meta
    name="viewport"
    content="width=device-width,initial-scale=1"
>

<title>Admin Dashboard - Anand Transport</title>

<style>

:root{
--red:#b40000;
--gold:#f0a900;
--bg:#f5f7fb;
--ink:#172033;
--muted:#6b7280;
--line:#e6e8ef;
--green:#14804a;
--blue:#1769aa;
}

*{
box-sizing:border-box;
}

body{
margin:0;
font-family:Arial,Helvetica,sans-serif;
background:var(--bg);
color:var(--ink);
}

.nav{
background:white;
border-bottom:3px solid var(--gold);
min-height:78px;
display:flex;
align-items:center;
justify-content:space-between;
padding:12px 4%;
gap:20px;
}

.brand{
display:flex;
align-items:center;
gap:12px;
}

.logo{
width:52px;
height:52px;
border-radius:12px;
background:linear-gradient(
135deg,
#e51b00,
#ffb000
);
display:grid;
place-items:center;
color:white;
font-weight:900;
font-size:18px;
box-shadow:0 3px 8px #bbb;
}

.brand h1{
font-size:21px;
margin:0;
color:#b00000;
}

.brand small{
display:block;
margin-top:2px;
color:#555;
}

.navlinks{
display:flex;
gap:16px;
align-items:center;
flex-wrap:wrap;
}

.navlinks a{
color:#161616;
text-decoration:none;
font-weight:700;
font-size:13px;
}

.wrap{
max-width:1450px;
margin:auto;
padding:30px 4% 50px;
}

.top{
display:flex;
justify-content:space-between;
align-items:center;
gap:20px;
margin-bottom:24px;
}

.top h2{
margin:0;
font-size:28px;
}

.top p{
margin:7px 0 0;
color:var(--muted);
}

.actions{
display:flex;
gap:9px;
flex-wrap:wrap;
}

.btn{
display:inline-flex;
align-items:center;
gap:7px;
text-decoration:none;
border:0;
border-radius:9px;
padding:11px 15px;
font-weight:800;
cursor:pointer;
}

.primary{
background:var(--red);
color:white;
}

.secondary{
background:white;
color:var(--ink);
border:1px solid var(--line);
}

.gold{
background:#fff4cf;
color:#7b5200;
border:1px solid #f2d88c;
}

.stats{
display:grid;
grid-template-columns:repeat(4,1fr);
gap:16px;
margin-bottom:22px;
}

.stat{
background:white;
border:1px solid var(--line);
border-radius:14px;
padding:20px;
box-shadow:0 3px 12px #00000008;
}

.label{
color:var(--muted);
font-size:13px;
font-weight:700;
}

.num{
font-size:29px;
font-weight:900;
margin-top:8px;
}

.red{
color:var(--red);
}

.blue{
color:var(--blue);
}

.green{
color:var(--green);
}

.card{
background:white;
border:1px solid var(--line);
border-radius:14px;
box-shadow:0 3px 12px #00000008;
overflow:hidden;
}

.cardhead{
padding:17px 20px;
border-bottom:1px solid var(--line);
display:flex;
justify-content:space-between;
align-items:center;
gap:15px;
}

.cardhead h3{
margin:0;
}

.search{
padding:9px 12px;
border:1px solid #d8dce5;
border-radius:8px;
min-width:230px;
}

.tablewrap{
overflow:auto;
}

table{
width:100%;
border-collapse:collapse;
min-width:1050px;
}

th,
td{
text-align:left;
padding:13px 12px;
border-bottom:1px solid var(--line);
font-size:13px;
vertical-align:top;
}

th{
background:#fafafa;
color:#596174;
font-size:12px;
text-transform:uppercase;
}

.badge{
display:inline-block;
padding:5px 9px;
border-radius:999px;
font-size:11px;
font-weight:800;
background:#eee;
}

.badge.booked{
background:#fff0cf;
color:#8a5a00;
}

.badge.transit{
background:#e7f1ff;
color:#125a9c;
}

.badge.delivered{
background:#e5f8ee;
color:#08703c;
}

.actions-cell{
display:flex;
gap:6px;
flex-wrap:wrap;
}

.mini{
padding:7px 9px;
border-radius:7px;
font-size:11px;
font-weight:800;
text-decoration:none;
border:1px solid var(--line);
background:white;
color:#222;
}

.mini.pdf{
background:#fff4cf;
color:#775000;
}

.mini.edit{
background:#e9f3ff;
color:#14598f;
}

.mini.receipt{
background:#e7f8ee;
color:#08703c;
}

.mini.delete{
background:#fff0f0;
color:#a00000;
}

.flash{
background:#e9f8ef;
color:#126b3d;
border:1px solid #bde8ce;
border-radius:10px;
padding:12px 15px;
margin-bottom:18px;
font-weight:700;
}

@media(max-width:900px){

.stats{
grid-template-columns:repeat(2,1fr);
}

.top{
align-items:flex-start;
flex-direction:column;
}

}

@media(max-width:560px){

.stats{
grid-template-columns:1fr;
}

.nav{
align-items:flex-start;
flex-direction:column;
}

}

</style>

</head>

<body>

<header class="nav">

<div class="brand">

<div class="logo">
ATC
</div>

<div>

<h1>Anand Transport Company</h1>

<small>
Reliable • Fast • Nationwide
</small>

</div>

</div>

<nav class="navlinks">

<a href="/">Home</a>

<a href="/">Track Shipment</a>

<a href="/about">About Us</a>

<a href="{{ url_for('money_receipt') }}">
Money Receipt
</a>

<a href="{{ url_for('change_credentials') }}">
Change Login
</a>

<a href="{{ url_for('logout') }}">
Logout
</a>

</nav>

</header>


<main class="wrap">


<div class="top">

<div>

<h2>
Admin Dashboard
</h2>

<p>
Welcome, {{ username }}.
Manage bookings, shipments and tracking.
</p>

</div>


<div class="actions">

<a
class="btn primary"
href="{{ url_for('new_shipment') }}"
>
＋ New Booking
</a>

<a
class="btn gold"
href="{{ url_for('money_receipt') }}"
>
₹ Money Receipt
</a>

<a
class="btn secondary"
href="{{ url_for('admin') }}"
>
↻ Refresh
</a>

</div>

</div>


{% with messages=get_flashed_messages() %}

{% if messages %}

{% for m in messages %}

<div class="flash">
{{ m }}
</div>

{% endfor %}

{% endif %}

{% endwith %}


<section class="stats">

<div class="stat">

<div class="label">
TOTAL SHIPMENTS
</div>

<div class="num">
{{ total }}
</div>

</div>


<div class="stat">

<div class="label">
BOOKED
</div>

<div class="num red">
{{ booked }}
</div>

</div>


<div class="stat">

<div class="label">
IN TRANSIT
</div>

<div class="num blue">
{{ in_transit }}
</div>

</div>


<div class="stat">

<div class="label">
DELIVERED
</div>

<div class="num green">
{{ delivered }}
</div>

</div>

</section>


<section class="card">


<div class="cardhead">

<h3>
Shipment Management
</h3>

<input
class="search"
id="search"
placeholder="Search GR / route / name..."
>

</div>


<div class="tablewrap">

<table id="shipTable">

<thead>

<tr>

<th>GR / Docket</th>
<th>Route</th>
<th>Consignor</th>
<th>Consignee</th>
<th>PKG</th>
<th>Weight</th>
<th>Amount</th>
<th>Status</th>
<th>Updated</th>
<th>Actions</th>

</tr>

</thead>


<tbody>

{% for s in shipments %}

<tr>

<td>

<strong>
{{ s.docket }}
</strong>

<br>

<small>
{{ s.booking_date }}
</small>

</td>


<td>

{{ s.source }} → {{ s.destination }}

<br>

<small>
{{ s.location or '' }}
</small>

</td>


<td>

{{ s.consignor or '-' }}

<br>

<small>
{{ s.consignor_contact or '' }}
</small>

</td>


<td>

{{ s.consignee or '-' }}

<br>

<small>
{{ s.consignee_contact or '' }}
</small>

</td>


<td>
{{ s.packages }}
</td>


<td>
{{ s.weight or '-' }}
</td>


<td>

₹ {{ s.amount or '0' }}

<br>

<small>
    {{ s.freight_basis or 'Not Set' }}
</small>

</td>


<td>

{% if s.status == 'Booked' %}

<span class="badge booked">
Booked
</span>

{% elif s.status == 'Delivered' %}

<span class="badge delivered">
Delivered
</span>

{% elif s.status == 'In Transit' %}

<span class="badge transit">
In Transit
</span>

{% else %}

<span class="badge">
{{ s.status }}
</span>

{% endif %}

</td>


<td>
{{ s.updated_at }}
</td>


<td>

<div class="actions-cell">


<a
class="mini pdf"
href="{{ url_for('shipment_pdf', sid=s.id) }}"
>
PDF
</a>


<a
class="mini edit"
href="{{ url_for('edit_shipment', sid=s.id) }}"
>
Edit
</a>


<a
class="mini receipt"
href="{{ url_for('money_receipt', docket=s.docket) }}"
>
Receipt
</a>


<form
method="POST"
action="{{ url_for('delete_shipment', sid=s.id) }}"
onsubmit="return confirm('Delete this shipment?')"
>

<button
class="mini delete"
type="submit"
>
Delete
</button>

</form>


</div>

</td>

</tr>

{% else %}

<tr>

<td
colspan="10"
style="text-align:center;padding:40px"
>
No shipments found.
</td>

</tr>

{% endfor %}

</tbody>

</table>

</div>

</section>


<div
style="
margin-top:30px;
text-align:center;
color:#777;
font-size:12px;
"
>

ANAND TRANSPORT CARRIER
•
GST ID {{ transport_gst }}
•
{{ transport_helpline }}

</div>


</main>


<script>

const q =
document.getElementById('search');

q.addEventListener(
'input',
function(){

const v =
q.value.toLowerCase();

document
.querySelectorAll(
'#shipTable tbody tr'
)
.forEach(
function(r){

r.style.display =
r.innerText
.toLowerCase()
.includes(v)
? ''
: 'none';

}
);

}
);

</script>

</body>

</html>
'''


# =========================================================
# ADMIN
# =========================================================

@app.route("/admin")
@login_required
def admin():

    con = db()
    cur = con.cursor()

    # =========================================================
    # DATE-WISE REPORT FILTER
    # =========================================================

    from_date = request.args.get("from_date", "").strip()
    to_date = request.args.get("to_date", "").strip()

    # Default: show all shipments
    shipments_query = """
        SELECT *
        FROM shipments
    """

    params = []

    # If both dates are selected, filter by booking date
    if from_date and to_date:
        shipments_query += """
            WHERE DATE(booking_date) BETWEEN %s AND %s
        """
        params = [from_date, to_date]

    elif from_date:
        shipments_query += """
            WHERE DATE(booking_date) >= %s
        """
        params = [from_date]

    elif to_date:
        shipments_query += """
            WHERE DATE(booking_date) <= %s
        """
        params = [to_date]

    shipments_query += """
        ORDER BY updated_at DESC
    """

    cur.execute(shipments_query, params)
    shipments = cur.fetchall()

    # =========================================================
    # SUMMARY COUNTS
    # =========================================================

    if from_date and to_date:
        date_condition = """
            WHERE DATE(booking_date) BETWEEN %s AND %s
        """
        date_params = [from_date, to_date]

    elif from_date:
        date_condition = """
            WHERE DATE(booking_date) >= %s
        """
        date_params = [from_date]

    elif to_date:
        date_condition = """
            WHERE DATE(booking_date) <= %s
        """
        date_params = [to_date]

    else:
        date_condition = ""
        date_params = []

    # Total consignments / dockets
    cur.execute(
        f"""
        SELECT COUNT(*) AS c
        FROM shipments
        {date_condition}
        """,
        date_params
    )

    total = cur.fetchone()["c"]

    # Booked
    cur.execute(
        f"""
        SELECT COUNT(*) AS c
        FROM shipments
        {date_condition}
        {"AND" if date_condition else "WHERE"} status='Booked'
        """,
        date_params
    )

    booked = cur.fetchone()["c"]

    # In Transit
    cur.execute(
        f"""
        SELECT COUNT(*) AS c
        FROM shipments
        {date_condition}
        {"AND" if date_condition else "WHERE"} status='In Transit'
        """,
        date_params
    )

    in_transit = cur.fetchone()["c"]

    # Delivered
    cur.execute(
        f"""
        SELECT COUNT(*) AS c
        FROM shipments
        {date_condition}
        {"AND" if date_condition else "WHERE"} status='Delivered'
        """,
        date_params
    )

    delivered = cur.fetchone()["c"]

    # =========================================================
    # REPORT TOTALS
    # =========================================================

    # Total Packages
    cur.execute(
        f"""
        SELECT COALESCE(SUM(packages), 0) AS total_packages
        FROM shipments
        {date_condition}
        """,
        date_params
    )

    total_packages = cur.fetchone()["total_packages"] or 0

    # Total Weight
    cur.execute(
        f"""
        SELECT COALESCE(
    SUM(
        CASE
            WHEN TRIM(weight::text) = '' THEN 0
            ELSE CAST(weight AS NUMERIC)
        END
    ),
    0
) AS total_weight
FROM shipments
{date_condition}
        """,
        date_params
    )

    total_weight = cur.fetchone()["total_weight"] or 0

    # Total Amount
    # This includes amount regardless of Freight Basis:
    # Paid / TBB / To Pay
    cur.execute(
        f"""
        SELECT COALESCE(
            SUM(
                CASE
                    WHEN TRIM(amount::text) = '' THEN 0
                    ELSE CAST(amount AS NUMERIC)
                END
            ),
            0
        ) AS total_amount
        FROM shipments
        {date_condition}
        """,
        date_params
    )

    total_amount = cur.fetchone()["total_amount"] or 0

    # ============================================================
    # PAID / TBB / TO PAY BREAKUP
    # ============================================================

    cur.execute(
        f"""
        SELECT
            COALESCE(
                SUM(
                    CASE
                        WHEN freight_basis = 'Paid'
                        THEN
                            CASE
                                WHEN TRIM(amount::text) = '' THEN 0
                                ELSE CAST(amount AS NUMERIC)
                            END
                        ELSE 0
                    END
                ), 0
            ) AS paid_amount,

            COALESCE(
                SUM(
                    CASE
                        WHEN freight_basis = 'TBB'
                        THEN
                            CASE
                                WHEN TRIM(amount::text) = '' THEN 0
                                ELSE CAST(amount AS NUMERIC)
                            END
                        ELSE 0
                    END
                ), 0
            ) AS tbb_amount,

            COALESCE(
                SUM(
                    CASE
                        WHEN freight_basis = 'To Pay'
                        THEN
                            CASE
                                WHEN TRIM(amount::text) = '' THEN 0
                                ELSE CAST(amount AS NUMERIC)
                            END
                        ELSE 0
                    END
                ), 0
            ) AS to_pay_amount

        FROM shipments
        {date_condition}
        """,
        date_params
    )

    amount_breakup = cur.fetchone()

    paid_amount = amount_breakup["paid_amount"] or 0
    tbb_amount = amount_breakup["tbb_amount"] or 0
    to_pay_amount = amount_breakup["to_pay_amount"] or 0
    tbb_amount = amount_breakup["tbb_amount"] or 0
    to_pay_amount = amount_breakup["to_pay_amount"] or 0

    cur.close()
    con.close()

    return render_template_string(
        ADMIN_DASHBOARD_HTML,

        shipments=shipments,

        # Main dashboard
        total=total,
        booked=booked,
        in_transit=in_transit,
        delivered=delivered,

        # Date filter
        from_date=from_date,
        to_date=to_date,

        # Report totals
        total_packages=total_packages,
        total_weight=total_weight,
        total_amount=total_amount,

        # Amount breakup
        paid_amount=paid_amount,
        tbb_amount=tbb_amount,
        to_pay_amount=to_pay_amount,

        username=session.get(
            "admin_username",
            "Admin"
        ),

        transport_gst=TRANSPORT_GST,
        transport_helpline=TRANSPORT_HELPLINE
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

    if request.method == "GET":

        return render_template_string(
            BOOKING_FORM_HTML,
            today=datetime.now().strftime(
                "%Y-%m-%d"
            ),
            default_gr=generate_gr_no()
        )

    data = request.form

    docket = (
        data.get("docket", "").strip()
        or generate_gr_no()
    )

    booking_date = (
        data.get(
            "booking_date",
            ""
        ).strip()
        or datetime.now().strftime(
            "%Y-%m-%d"
        )
    )

    source = data.get(
        "source",
        ""
    ).strip()

    destination = data.get(
        "destination",
        ""
    ).strip()

    consignor = data.get(
        "consignor",
        ""
    ).strip()

    consignor_address = data.get(
        "consignor_address",
        ""
    ).strip()

    consignor_contact = data.get(
        "consignor_contact",
        ""
    ).strip()

    consignee = data.get(
        "consignee",
        ""
    ).strip()

    consignee_address = data.get(
        "consignee_address",
        ""
    ).strip()

    consignee_contact = data.get(
        "consignee_contact",
        ""
    ).strip()

    packages = int(
        data.get("packages") or 1
    )

    weight = data.get(
        "weight",
        ""
    ).strip()

    amount = data.get(
        "amount",
        ""
    ).strip()

    freight_basis = data.get(
        "freight_basis",
        "To Pay"
    ).strip() or "To Pay"

    goods_description = data.get(
        "goods_description",
        ""
    ).strip()

    expected_delivery = data.get(
        "expected_delivery",
        ""
    ).strip()

    remark = data.get(
        "remark",
        ""
    ).strip()

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    event_time = data.get(
        "event_time",
        ""
    ).strip() or datetime.now().strftime(
        "%H:%M"
    )

    manual_event_time = (
        f"{booking_date} "
        f"{event_time}:00"
    )

    if (
        not source
        or not destination
        or not consignor
        or not consignee
    ):

        flash(
            "Please fill From, To, Consignor and Consignee details."
        )

        return redirect(
            url_for("new_shipment")
        )

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
                updated_at,
                consignor_address,
                consignor_contact,
                consignee_address,
                consignee_contact,
                amount,
                freight_basis,
                goods_description
            )
            VALUES(
                %s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s
            )
            RETURNING id
            """,
            (
                docket,
                booking_date,
                source,
                destination,
                consignor,
                consignee,
                packages,
                weight,
                "Booked",
                source,
                expected_delivery,
                remark,
                now,
                now,
                consignor_address,
                consignor_contact,
                consignee_address,
                consignee_contact,
                amount,
                freight_basis,
                goods_description
            )
        )

        sid = cur.fetchone()["id"]

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
                source,
                "Shipment booked.",
                manual_event_time
            )
        )

        con.commit()

        flash(
            f"Booking {docket} created successfully."
        )

    except psycopg2.IntegrityError:

        con.rollback()

        flash(
            "GR / Consignment number already exists."
        )

    finally:

        cur.close()
        con.close()

    return redirect(
        url_for("admin")
    )


# =========================================================
# BOOKING FORM
# =========================================================

BOOKING_FORM_HTML = r'''
<!doctype html>

<html lang="en">

<head>

<meta charset="utf-8">

<meta
name="viewport"
content="width=device-width,initial-scale=1"
>

<title>New Booking - Anand Transport</title>

<style>

body{
margin:0;
font-family:Arial;
background:#f5f7fb;
color:#172033;
}

.nav{
height:78px;
background:#fff;
border-bottom:3px solid #f0a900;
display:flex;
justify-content:space-between;
align-items:center;
padding:0 4%;
}

.brand{
display:flex;
align-items:center;
gap:12px;
}

.logo{
width:52px;
height:52px;
border-radius:12px;
background:linear-gradient(
135deg,
#e51b00,
#ffb000
);
display:grid;
place-items:center;
color:#fff;
font-weight:900;
}

.brand h1{
font-size:20px;
color:#b00000;
margin:0;
}

.brand small{
color:#555;
}

.nav a{
text-decoration:none;
color:#111;
font-weight:700;
}

.wrap{
max-width:1100px;
margin:auto;
padding:28px 4% 50px;
}

.card{
background:white;
border:1px solid #e1e5ec;
border-radius:15px;
margin-bottom:18px;
overflow:hidden;
box-shadow:0 4px 18px #0000000b;
}

.ct{
padding:15px 20px;
background:#fff8e8;
border-bottom:1px solid #f1e0b4;
color:#8a5600;
font-weight:900;
}

.cb{
padding:20px;
}

.grid{
display:grid;
grid-template-columns:repeat(2,1fr);
gap:16px;
}

.grid3{
display:grid;
grid-template-columns:repeat(3,1fr);
gap:16px;
}

.field label{
display:block;
font-size:13px;
font-weight:800;
margin-bottom:6px;
}

.field input,
.field textarea,
.field select{
width:100%;
border:1px solid #d5d9e1;
border-radius:8px;
padding:11px;
font-size:14px;
box-sizing:border-box;
}

.field textarea{
min-height:80px;
resize:vertical;
}

.full{
grid-column:1/-1;
}

.actions{
display:flex;
justify-content:flex-end;
gap:10px;
}

.btn{
padding:12px 18px;
border-radius:9px;
font-weight:900;
text-decoration:none;
border:0;
cursor:pointer;
}

.primary{
background:#b40000;
color:#fff;
}

.secondary{
background:#fff;
color:#222;
border:1px solid #ddd;
}

.notice{
padding:13px 15px;
background:#eef6ff;
border:1px solid #cfe3fb;
border-radius:10px;
color:#155a8f;
font-size:13px;
font-weight:700;
margin-bottom:18px;
}

@media(max-width:700px){

.grid,
.grid3{
grid-template-columns:1fr;
}

.nav{
height:auto;
padding:12px 4%;
gap:10px;
}

}

</style>

</head>

<body>

<header class="nav">

<div class="brand">

<div class="logo">
ATC
</div>

<div>

<h1>
Anand Transport Company
</h1>

<small>
Reliable • Fast • Nationwide
</small>

</div>

</div>

<a href="{{ url_for('admin') }}">
← Admin Dashboard
</a>

</header>


<main class="wrap">

<h2>
New Shipment Booking
</h2>

<div class="notice">

After booking, shipment status will automatically be
<strong>BOOKED</strong>.

<br>

<strong>
Important:
</strong>
Amount will appear on the GR PDF only when
Freight Basis is <strong>To Pay</strong>.
For Paid/TBB, amount will remain only in website records.

</div>


<form method="POST">


<section class="card">

<div class="ct">
📦 Booking Details
</div>

<div class="cb">

<div class="grid3">


<div class="field">

<label>
Consignment / GR No.
</label>

<input
name="docket"
value="{{ default_gr }}"
required
>

</div>


<div class="field">

<label>
Booking Date
</label>

<input
type="date"
name="booking_date"
value="{{ today }}"
required
>

</div>


<div class="field">

<label>
Expected Delivery Date
</label>

<input
type="date"
name="expected_delivery"
>

</div>

</div>

</div>

</section>


<section class="card">

<div class="ct">
🚚 Route
</div>

<div class="cb">

<div class="grid">

<div class="field">

<label>
From
</label>

<input
name="source"
required
>

</div>


<div class="field">

<label>
To
</label>

<input
name="destination"
required
>

</div>

</div>

</div>

</section>


<section class="card">

<div class="ct">
👤 Consignor
</div>

<div class="cb">

<div class="grid">

<div class="field">

<label>
Consignor Name
</label>

<input
name="consignor"
required
>

</div>


<div class="field">

<label>
Contact Number
</label>

<input
name="consignor_contact"
>

</div>


<div class="field full">

<label>
Address
</label>

<textarea
name="consignor_address"
></textarea>

</div>

</div>

</div>

</section>


<section class="card">

<div class="ct">
👤 Consignee
</div>

<div class="cb">

<div class="grid">

<div class="field">

<label>
Consignee Name
</label>

<input
name="consignee"
required
>

</div>


<div class="field">

<label>
Contact Number
</label>

<input
name="consignee_contact"
>

</div>


<div class="field full">

<label>
Address
</label>

<textarea
name="consignee_address"
></textarea>

</div>

</div>

</div>

</section>


<section class="card">

<div class="ct">
📦 Goods & Charges
</div>

<div class="cb">

<div class="grid3">


<div class="field">

<label>
Packages
</label>

<input
type="number"
min="1"
name="packages"
value="1"
required
>

</div>


<div class="field">

<label>
Weight
</label>

<input
name="weight"
placeholder="e.g. 25 kg"
>

</div>


<div class="field">

<label>
Amount (₹)
</label>

<input
name="amount"
placeholder="e.g. 1250"
>

</div>


</div>


<div
class="grid"
style="margin-top:16px"
>


<div class="field">

<label>
Freight Basis
</label>

<select
name="freight_basis"
required
>

<option value="To Pay">
To Pay
</option>

<option value="Paid">
Paid
</option>

<option value="TBB">
TBB
</option>

</select>

</div>


<div class="field">

<label>
Goods Description
</label>

<input
name="goods_description"
placeholder="e.g. House Hold Goods"
>

</div>

</div>

</div>

</section>


<section class="card">

<div class="ct">
📝 Remarks
</div>

<div class="cb">

<div class="grid">

<div class="field">

<label>
Booking Time
</label>

<input
type="time"
name="event_time"
>

</div>


<div class="field">

<label>
Remark
</label>

<input
name="remark"
>

</div>

</div>

</div>

</section>


<div class="actions">

<a
class="btn secondary"
href="{{ url_for('admin') }}"
>
Cancel
</a>

<button
class="btn primary"
type="submit"
>
✓ Book Shipment
</button>

</div>

</form>

</main>

</body>

</html>
'''


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

    data = request.form

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    status = data.get(
        "status",
        "Booked"
    )

    location = data.get(
        "location",
        ""
    ).strip()

    remark = data.get(
        "remark",
        ""
    ).strip()

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
        f"{event_date} "
        f"{event_time}:00"
    )

    # -------------------------
    # UPDATE MASTER
    # -------------------------

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
            data.get("docket", "").strip(),
            data.get("booking_date", ""),
            data.get("source", "").strip(),
            data.get("destination", "").strip(),
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

    # -------------------------
    # ORIGINAL BOOKED EVENT
    # -------------------------

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

    # -------------------------
    # BOOKED
    # -------------------------

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
                    data.get(
                        "source",
                        ""
                    ).strip(),

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
                    data.get(
                        "source",
                        ""
                    ).strip(),
                    "Shipment booked.",
                    manual_event_time
                )
            )

    # -------------------------
    # OTHER STATUS
    # -------------------------

    else:

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
# MONEY RECEIPT NUMBER
# =========================================================

def generate_receipt_no(con=None, cur=None):

    # Fixed Money Receipt series as requested:
    # MR-202601-0001, MR-202601-0002, ...
    #
    # IMPORTANT: Do not use COUNT() here. COUNT() can generate a number
    # that already exists when a receipt was deleted or when two requests
    # arrive at nearly the same time. A transaction-level PostgreSQL
    # advisory lock + MAX() keeps the number unique.
    prefix = "MR-202601"

    own_connection = con is None or cur is None

    if own_connection:
        con = db()
        cur = con.cursor()

    try:
        # Serialize receipt-number generation for all app instances
        # using the same PostgreSQL database. The lock is held until
        # the current transaction commits/rolls back.
        cur.execute("SELECT pg_advisory_xact_lock(202601)")

        cur.execute(
            """
            SELECT COALESCE(
                MAX(
                    CASE
                        WHEN split_part(receipt_no, '-', 3) ~ '^[0-9]+$'
                        THEN CAST(split_part(receipt_no, '-', 3) AS INTEGER)
                        ELSE 0
                    END
                ),
                0
            ) AS max_no
            FROM money_receipts
            WHERE receipt_no LIKE %s
            """,
            (prefix + "-%",)
        )

        row = cur.fetchone()
        max_no = int(row.get("max_no", 0) or 0) if row else 0
        next_no = max_no + 1

        return f"{prefix}-{next_no:04d}"

    finally:
        if own_connection:
            cur.close()
            con.close()

# =========================================================
# MONEY RECEIPT
# =========================================================

@app.route(
    "/admin/money-receipt",
    methods=["GET", "POST"]
)
@login_required
def money_receipt():

    docket = request.args.get(
        "docket",
        ""
    ).strip()

    shipment = None

    if docket:

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

        cur.close()
        con.close()

    if request.method == "POST":

        docket = request.form.get(
            "docket",
            ""
        ).strip()

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

        if not shipment:

            cur.close()
            con.close()

            flash(
                "GR / Consignment number not found."
            )

            return redirect(
                url_for("money_receipt")
            )

        freight = money_value(
            request.form.get("freight")
        )

        handling = money_value(
            request.form.get("handling")
        )

        door_delivery = money_value(
            request.form.get("door_delivery")
        )

        receipt_charge = money_value(
            request.form.get("receipt_charge")
        )

        damage = money_value(
            request.form.get("damage")
        )

        additional_charge = money_value(
            request.form.get("additional_charge")
        )

        total = (
            freight
            + handling
            + door_delivery
            + receipt_charge
            + damage
            + additional_charge
        )

        note = request.form.get(
            "note",
            ""
        ).strip()

        # Generate the receipt number inside the SAME transaction used
        # for the INSERT. This prevents duplicate receipt numbers.
        receipt_no = generate_receipt_no(
            con=con,
            cur=cur
        )

        created_at = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        cur.execute(
            """
            INSERT INTO money_receipts
            (
                receipt_no,
                shipment_id,
                docket,
                freight,
                handling,
                door_delivery,
                receipt_charge,
                damage,
                additional_charge,
                total,
                note,
                created_at
            )
            VALUES(
                %s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,%s
            )
            RETURNING id
            """,
            (
                receipt_no,
                shipment["id"],
                shipment["docket"],
                freight,
                handling,
                door_delivery,
                receipt_charge,
                damage,
                additional_charge,
                total,
                note,
                created_at
            )
        )

        rid = cur.fetchone()["id"]

        con.commit()

        cur.close()
        con.close()

        flash(
            f"Money Receipt {receipt_no} generated successfully."
        )

        return redirect(
            url_for(
                "money_receipt_pdf",
                rid=rid
            )
        )

    return render_template_string(
        MONEY_RECEIPT_HTML,
        shipment=shipment,
        docket=docket,
        default_receipt=generate_receipt_no()
    )


# =========================================================
# MONEY RECEIPT HTML
# =========================================================

MONEY_RECEIPT_HTML = r'''
<!doctype html>

<html lang="en">

<head>

<meta charset="utf-8">

<meta
name="viewport"
content="width=device-width,initial-scale=1"
>

<title>Money Receipt - Anand Transport</title>

<style>

*{
box-sizing:border-box;
}

body{
margin:0;
font-family:Arial,Helvetica,sans-serif;
background:#f5f7fb;
color:#172033;
}

.nav{
background:white;
border-bottom:3px solid #f0a900;
min-height:78px;
display:flex;
align-items:center;
justify-content:space-between;
padding:12px 4%;
gap:15px;
}

.brand{
display:flex;
align-items:center;
gap:12px;
}

.logo{
width:52px;
height:52px;
border-radius:12px;
background:linear-gradient(
135deg,
#e51b00,
#ffb000
);
display:grid;
place-items:center;
color:white;
font-weight:900;
}

.brand h1{
margin:0;
font-size:20px;
color:#b00000;
}

.brand small{
color:#555;
}

.nav a{
text-decoration:none;
font-weight:700;
color:#111;
}

.wrap{
max-width:1050px;
margin:auto;
padding:30px 4% 60px;
}

.page-title{
display:flex;
justify-content:space-between;
align-items:center;
gap:15px;
margin-bottom:20px;
}

.page-title h2{
margin:0;
font-size:28px;
}

.card{
background:white;
border:1px solid #e2e5eb;
border-radius:15px;
overflow:hidden;
margin-bottom:18px;
box-shadow:0 4px 18px #00000009;
}

.card-title{
padding:15px 20px;
background:#fff8e8;
border-bottom:1px solid #f1e0b4;
font-weight:900;
color:#8a5600;
}

.card-body{
padding:20px;
}

.search-row{
display:flex;
gap:10px;
}

input,
textarea{
width:100%;
padding:11px;
border:1px solid #d4d8e0;
border-radius:8px;
font-size:14px;
}

button,
.btn{
padding:11px 17px;
border:0;
border-radius:8px;
font-weight:900;
cursor:pointer;
text-decoration:none;
display:inline-block;
}

.search-btn{
background:#b40000;
color:white;
white-space:nowrap;
}

.info{
display:grid;
grid-template-columns:repeat(3,1fr);
gap:12px;
}

.info-box{
background:#f8f9fb;
border:1px solid #e3e6eb;
border-radius:9px;
padding:12px;
}

.info-box span{
display:block;
font-size:11px;
color:#777;
font-weight:700;
margin-bottom:4px;
}

.info-box strong{
font-size:14px;
}

.charges{
display:grid;
grid-template-columns:repeat(2,1fr);
gap:15px;
}

.charge label{
display:block;
font-size:13px;
font-weight:800;
margin-bottom:6px;
}

.total{
margin-top:18px;
padding:18px;
background:#fff7dd;
border:1px solid #f0d68c;
border-radius:10px;
display:flex;
justify-content:space-between;
align-items:center;
font-size:20px;
font-weight:900;
color:#7a5000;
}

.actions{
display:flex;
justify-content:flex-end;
gap:10px;
margin-top:18px;
}

.cancel{
background:white;
border:1px solid #ddd;
color:#222;
}

.generate{
background:#b40000;
color:white;
}

.note{
margin-top:15px;
}

@media(max-width:700px){

.info,
.charges{
grid-template-columns:1fr;
}

.search-row{
flex-direction:column;
}

.page-title{
align-items:flex-start;
flex-direction:column;
}

}

</style>

</head>

<body>


<header class="nav">

<div class="brand">

<div class="logo">
ATC
</div>

<div>

<h1>
Anand Transport Company
</h1>

<small>
Money Receipt Section
</small>

</div>

</div>

<a href="{{ url_for('admin') }}">
← Admin Dashboard
</a>

</header>


<main class="wrap">


<div class="page-title">

<div>

<h2>
₹ Money Receipt
</h2>

<p>
Generate receipt for freight and additional charges.
</p>

</div>

</div>


<section class="card">

<div class="card-title">
🔎 Find Shipment
</div>

<div class="card-body">

<form method="GET">

<div class="search-row">

<input
name="docket"
placeholder="Enter Consignment / GR No."
value="{{ docket }}"
required
>

<button
class="search-btn"
type="submit"
>
Search Shipment
</button>

</div>

</form>

</div>

</section>


{% if shipment %}


<section class="card">

<div class="card-title">
📦 Shipment Details
</div>

<div class="card-body">

<div class="info">


<div class="info-box">

<span>
GR / CONSIGNMENT
</span>

<strong>
{{ shipment.docket }}
</strong>

</div>


<div class="info-box">

<span>
BOOKING DATE
</span>

<strong>
{{ shipment.booking_date }}
</strong>

</div>


<div class="info-box">

<span>
STATUS
</span>

<strong>
{{ shipment.status }}
</strong>

</div>


<div class="info-box">

<span>
FROM
</span>

<strong>
{{ shipment.source }}
</strong>

</div>


<div class="info-box">

<span>
TO
</span>

<strong>
{{ shipment.destination }}
</strong>

</div>


<div class="info-box">

<span>
CONSIGNOR
</span>

<strong>
{{ shipment.consignor or '-' }}
</strong>

</div>


<div class="info-box">

<span>
CONSIGNEE
</span>

<strong>
{{ shipment.consignee or '-' }}
</strong>

</div>


<div class="info-box">

<span>
PACKAGES
</span>

<strong>
{{ shipment.packages }}
</strong>

</div>


<div class="info-box">

<span>
WEIGHT
</span>

<strong>
{{ shipment.weight or '-' }}
</strong>

</div>


</div>

</div>

</section>


<section class="card">

<div class="card-title">
💰 Charges
</div>

<div class="card-body">

<form
method="POST"
>

<input
type="hidden"
name="docket"
value="{{ shipment.docket }}"
>


<div class="charges">


<div class="charge">

<label>
Freight
</label>

<input
class="amount"
type="number"
step="0.01"
min="0"
name="freight"
value="{{ shipment.amount or '0' }}"
>
</div>


<div class="charge">

<label>
Handling
</label>

<input
class="amount"
type="number"
step="0.01"
min="0"
name="handling"
value="0"
>
</div>


<div class="charge">

<label>
Door Delivery
</label>

<input
class="amount"
type="number"
step="0.01"
min="0"
name="door_delivery"
value="0"
>
</div>


<div class="charge">

<label>
Receipt
</label>

<input
class="amount"
type="number"
step="0.01"
min="0"
name="receipt_charge"
value="0"
>
</div>


<div class="charge">

<label>
Damage
</label>

<input
class="amount"
type="number"
step="0.01"
min="0"
name="damage"
value="0"
>
</div>


<div class="charge">

<label>
Additional Charge
</label>

<input
class="amount"
type="number"
step="0.01"
min="0"
name="additional_charge"
value="0"
>
</div>


</div>


<label style="
display:block;
font-size:13px;
font-weight:800;
margin-top:18px;
margin-bottom:6px;
">
Note / Remark
</label>

<textarea
class="note"
name="note"
placeholder="Optional note"
></textarea>


<div class="total">

<span>
TOTAL
</span>

<span>
₹ <span id="total">0.00</span>
</span>

</div>


<div class="actions">

<a
class="btn cancel"
href="{{ url_for('admin') }}"
>
Cancel
</a>

<button
class="btn generate"
type="submit"
>
Generate Money Receipt
</button>

</div>


</form>

</div>

</section>

{% endif %}


</main>


<script>

function calculateTotal(){

let total = 0;

document
.querySelectorAll(".amount")
.forEach(function(input){

total +=
parseFloat(input.value) || 0;

});

document.getElementById(
"total"
).innerText =
total.toFixed(2);

}

document
.querySelectorAll(".amount")
.forEach(function(input){

input.addEventListener(
"input",
calculateTotal
);

});

calculateTotal();

</script>

</body>

</html>
'''


# =========================================================
# MONEY RECEIPT PDF
# =========================================================

@app.route(
    "/admin/money-receipt/<int:rid>/pdf"
)
@login_required
def money_receipt_pdf(rid):

    con = db()
    cur = con.cursor()

    cur.execute(
        """
        SELECT
            mr.*,

            s.booking_date,
            s.source,
            s.destination,
            s.consignor,
            s.consignee,
            s.packages,
            s.weight,
            s.status,
            s.freight_basis

        FROM money_receipts mr

        JOIN shipments s
        ON s.id=mr.shipment_id

        WHERE mr.id=%s
        """,
        (rid,)
    )

    receipt = cur.fetchone()

    cur.close()
    con.close()

    if not receipt:

        return "Money Receipt not found", 404

    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=25,
        bottomMargin=30
    )

    styles = getSampleStyleSheet()

    normal = ParagraphStyle(
        "ReceiptNormal",
        parent=styles["Normal"],
        fontSize=9,
        leading=12
    )

    small = ParagraphStyle(
        "ReceiptSmall",
        parent=styles["Normal"],
        fontSize=8,
        leading=10
    )

    heading = ParagraphStyle(
        "ReceiptHeading",
        parent=styles["Heading2"],
        fontSize=11,
        leading=13,
        textColor=colors.HexColor("#b00000"),
        spaceAfter=5
    )

    center = ParagraphStyle(
        "ReceiptCenter",
        parent=normal,
        alignment=TA_CENTER
    )

    right = ParagraphStyle(
        "ReceiptRight",
        parent=normal,
        alignment=TA_RIGHT
    )

    story = []

    pdf_header(
        story,
        styles
    )

    # =====================================================
    # RECEIPT TITLE
    # =====================================================

    title = Table(
        [
            [
                Paragraph(
                    "<b>MONEY RECEIPT</b>",
                    ParagraphStyle(
                        "MoneyTitle",
                        fontSize=17,
                        textColor=colors.white,
                        alignment=TA_CENTER
                    )
                )
            ]
        ],
        colWidths=[524]
    )

    title.setStyle(
        TableStyle([
            (
                "BACKGROUND",
                (0, 0),
                (-1, -1),
                colors.HexColor("#b00000")
            ),
            (
                "BOX",
                (0, 0),
                (-1, -1),
                1,
                colors.HexColor("#f0a900")
            ),
            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                8
            ),
            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                8
            )
        ])
    )

    story.append(title)

    story.append(
        Spacer(1, 10)
    )

    # =====================================================
    # RECEIPT INFO
    # =====================================================

    receipt_info = Table(
        [
            [
                _pdf_paragraph(
                    "Receipt No.",
                    normal
                ),

                _pdf_paragraph(
                    receipt["receipt_no"],
                    normal
                ),

                _pdf_paragraph(
                    "Date",
                    normal
                ),

                _pdf_paragraph(
                    format_date_ddmmyyyy(
                        str(
                            receipt["created_at"]
                        )[:10]
                    ),
                    normal
                )
            ],

            [
                _pdf_paragraph(
                    "GR / Consignment",
                    normal
                ),

                _pdf_paragraph(
                    receipt["docket"],
                    normal
                ),

                _pdf_paragraph(
                    "Freight Basis",
                    normal
                ),

                _pdf_paragraph(
                    receipt.get(
                        "freight_basis"
                    ) or "-",
                    normal
                )
            ]
        ],
        colWidths=[
            100,
            174,
            100,
            150
        ]
    )

    receipt_info.setStyle(
        TableStyle([
            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.5,
                colors.HexColor("#cccccc")
            ),
            (
                "BACKGROUND",
                (0, 0),
                (0, -1),
                colors.HexColor("#f7f7f7")
            ),
            (
                "BACKGROUND",
                (2, 0),
                (2, -1),
                colors.HexColor("#f7f7f7")
            ),
            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "TOP"
            ),
            (
                "LEFTPADDING",
                (0, 0),
                (-1, -1),
                6
            ),
            (
                "RIGHTPADDING",
                (0, 0),
                (-1, -1),
                6
            ),
            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                6
            ),
            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                6
            )
        ])
    )

    story.append(receipt_info)

    story.append(
        Spacer(1, 10)
    )

    # =====================================================
    # CUSTOMER / SHIPMENT
    # =====================================================

    customer = Table(
        [
            [
                Paragraph(
                    "SHIPMENT DETAILS",
                    heading
                )
            ],

            [
                _pdf_paragraph(
                    f"Consignor: "
                    f"{receipt.get('consignor') or '-'}",
                    normal
                )
            ],

            [
                _pdf_paragraph(
                    f"Consignee: "
                    f"{receipt.get('consignee') or '-'}",
                    normal
                )
            ],

            [
                _pdf_paragraph(
                    f"Route: "
                    f"{receipt.get('source') or '-'} "
                    f" → "
                    f"{receipt.get('destination') or '-'}",
                    normal
                )
            ],

            [
                _pdf_paragraph(
                    f"Packages: "
                    f"{receipt.get('packages') or '-'}"
                    f"     Weight: "
                    f"{receipt.get('weight') or '-'}",
                    normal
                )
            ]
        ],
        colWidths=[524]
    )

    customer.setStyle(
        TableStyle([
            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.5,
                colors.HexColor("#cccccc")
            ),
            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.HexColor("#f7f7f7")
            ),
            (
                "LEFTPADDING",
                (0, 0),
                (-1, -1),
                7
            ),
            (
                "RIGHTPADDING",
                (0, 0),
                (-1, -1),
                7
            ),
            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                5
            ),
            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                5
            )
        ])
    )

    story.append(customer)

    story.append(
        Spacer(1, 10)
    )

    # =====================================================
    # CHARGES
    # =====================================================

    charge_rows = [

        [
            Paragraph(
                "<b>CHARGE</b>",
                small
            ),
            Paragraph(
                "<b>AMOUNT</b>",
                small
            )
        ],

        [
            _pdf_paragraph(
                "Freight",
                normal
            ),
            _pdf_paragraph(
                "₹ " +
                money_text(
                    receipt["freight"]
                ),
                right
            )
        ],

        [
            _pdf_paragraph(
                "Handling",
                normal
            ),
            _pdf_paragraph(
                "₹ " +
                money_text(
                    receipt["handling"]
                ),
                right
            )
        ],

        [
            _pdf_paragraph(
                "Door Delivery",
                normal
            ),
            _pdf_paragraph(
                "₹ " +
                money_text(
                    receipt["door_delivery"]
                ),
                right
            )
        ],

        [
            _pdf_paragraph(
                "Receipt",
                normal
            ),
            _pdf_paragraph(
                "₹ " +
                money_text(
                    receipt["receipt_charge"]
                ),
                right
            )
        ],

        [
            _pdf_paragraph(
                "Damage",
                normal
            ),
            _pdf_paragraph(
                "₹ " +
                money_text(
                    receipt["damage"]
                ),
                right
            )
        ],

        [
            _pdf_paragraph(
                "Additional Charge",
                normal
            ),
            _pdf_paragraph(
                "₹ " +
                money_text(
                    receipt["additional_charge"]
                ),
                right
            )
        ],

        [
            Paragraph(
                "<b>TOTAL</b>",
                normal
            ),

            Paragraph(
                "<b>₹ "
                + money_text(
                    receipt["total"]
                )
                + "</b>",
                right
            )
        ]
    ]

    charges = Table(
        charge_rows,
        colWidths=[
            370,
            154
        ]
    )

    charges.setStyle(
        TableStyle([
            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.5,
                colors.HexColor("#cccccc")
            ),
            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.HexColor("#f7f7f7")
            ),
            (
                "BACKGROUND",
                (0, -1),
                (-1, -1),
                colors.HexColor("#fff4cf")
            ),
            (
                "LEFTPADDING",
                (0, 0),
                (-1, -1),
                7
            ),
            (
                "RIGHTPADDING",
                (0, 0),
                (-1, -1),
                7
            ),
            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                6
            ),
            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                6
            )
        ])
    )

    story.append(charges)

    story.append(
        Spacer(1, 10)
    )

    if receipt.get("note"):

        story.append(
            Paragraph(
                "NOTE",
                heading
            )
        )

        story.append(
            _pdf_paragraph(
                receipt["note"],
                normal
            )
        )

        story.append(
            Spacer(1, 15)
        )

    story.append(
        Paragraph(
            "Received with thanks.",
            normal
        )
    )

    story.append(
        Spacer(1, 30)
    )

    story.append(
        Paragraph(
            "For ANAND TRANSPORT CARRIER",
            right
        )
    )

    doc.build(story)

    buffer.seek(0)

    filename = (
        f"{receipt['receipt_no']}_Money_Receipt.pdf"
    )

    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf"
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
