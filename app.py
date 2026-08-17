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
        "shipment_value": "TEXT",
        "tbb_customer_code": "TEXT",

        "goods_description": "TEXT",
        "eway_bill_no": "TEXT"
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
    # UPDATED BOOKING / CHARGE COLUMNS
    # -------------------------
    booking_columns = {
        "consignor_gstin": "TEXT",
        "consignee_gstin": "TEXT",
        "invoice_ref": "TEXT",
        "actual_weight": "TEXT",
        "charge_weight": "TEXT",
        "freight_charge": "TEXT DEFAULT '0'",
        "handling_charge": "TEXT DEFAULT '0'",
        "dd_charge": "TEXT DEFAULT '0'",
        "other_charge": "TEXT DEFAULT '0'",
        "charge_total": "TEXT DEFAULT '0'",
        "gst_amount": "TEXT DEFAULT '0'",
        "grand_total": "TEXT DEFAULT '0'",
        "charges_approved": "BOOLEAN DEFAULT FALSE"
    }
    for column, sql_type in booking_columns.items():
        cur.execute(f"ALTER TABLE shipments ADD COLUMN IF NOT EXISTS {column} {sql_type}")

    # -------------------------
    # TBB CUSTOMERS
    # -------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tbb_customers(
            id SERIAL PRIMARY KEY,
            code TEXT UNIQUE NOT NULL,
            customer_name TEXT NOT NULL,
            mobile TEXT,
            gstin TEXT,
            address TEXT,
            aadhaar_no TEXT,
            pan_no TEXT,
            aadhaar_filename TEXT,
            aadhaar_data BYTEA,
            pan_filename TEXT,
            pan_data BYTEA,
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

    # Demo shipment intentionally not created.

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
    shipment_value = shipment.get("shipment_value") or "-"
    tbb_customer_code = shipment.get("tbb_customer_code") or "-"

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
                    "Shipment Value",
                    normal
                ),

                _pdf_paragraph(
                    "₹ " + money_text(shipment_value)
                    if shipment_value != "-"
                    else "-",
                    normal
                ),

                _pdf_paragraph(
                    "TBB Customer Code",
                    normal
                ),

                _pdf_paragraph(
                    tbb_customer_code if freight_basis == "TBB" else "-",
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
                    "Shipment Value",
                    normal
                ),

                _pdf_paragraph(
                    "₹ " + money_text(shipment_value)
                    if shipment_value != "-"
                    else "-",
                    normal
                ),

                _pdf_paragraph(
                    "TBB Customer Code",
                    normal
                ),

                _pdf_paragraph(
                    tbb_customer_code if freight_basis == "TBB" else "-",
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
# BOOKING REPORT
# =========================================================

BOOKING_REPORT_HTML = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Booking Report - Anand Transport</title>
<style>
body{margin:0;font-family:Arial,Helvetica,sans-serif;background:#f5f7fb;color:#172033}
.wrap{max-width:1500px;margin:auto;padding:28px 4% 50px}
.nav{background:#fff;border-bottom:3px solid #f0a900;min-height:70px;display:flex;align-items:center;justify-content:space-between;padding:12px 4%;gap:20px}
.brand{display:flex;align-items:center;gap:12px}.logo{width:52px;height:52px;border-radius:12px;background:linear-gradient(135deg,#e51b00,#ffb000);display:grid;place-items:center;color:#fff;font-weight:900}
.brand h1{font-size:21px;margin:0;color:#b00000}.brand small{color:#555}.nav a{color:#111;text-decoration:none;font-weight:800;font-size:13px}
.filter,.card,.stat{background:#fff;border:1px solid #e6e8ef;border-radius:14px;box-shadow:0 3px 12px #00000008}
.filter{padding:18px;margin-bottom:20px}.row{display:flex;gap:12px;align-items:end;flex-wrap:wrap}.field{min-width:190px}
.field label{display:block;font-size:12px;font-weight:800;color:#6b7280;margin-bottom:6px}.field input{width:100%;padding:10px 12px;border:1px solid #d8dce5;border-radius:8px;font-size:14px}
.btn{display:inline-flex;align-items:center;justify-content:center;text-decoration:none;border:0;border-radius:9px;padding:11px 15px;font-weight:800;cursor:pointer;min-height:42px}
.primary{background:#b40000;color:#fff}.secondary{background:#fff;color:#172033;border:1px solid #e6e8ef}
.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:20px}.stat{padding:17px}
.label{color:#6b7280;font-size:12px;font-weight:800;text-transform:uppercase}.num{font-size:25px;font-weight:900;margin-top:7px}.card{overflow:hidden}
.head{padding:17px 20px;border-bottom:1px solid #e6e8ef;display:flex;justify-content:space-between}
.tablewrap{overflow:auto}.table{width:100%;border-collapse:collapse;min-width:1250px}.table th,.table td{padding:12px 10px;border-bottom:1px solid #e6e8ef;font-size:13px;text-align:left}
.table th{background:#fafafa;color:#596174;font-size:11px;text-transform:uppercase;white-space:nowrap}.center{text-align:center!important}.amount{text-align:right!important;font-weight:800}
.total td{background:#fff8e8;border-top:2px solid #f0a900;font-weight:900}.badge{display:inline-block;padding:5px 9px;border-radius:999px;font-size:11px;font-weight:900}
.paid{background:#e5f8ee;color:#08703c}.tbb{background:#fff4cf;color:#7b5200}.topay{background:#e7f1ff;color:#125a9c}
@media(max-width:900px){.summary{grid-template-columns:repeat(2,1fr)}}@media(max-width:560px){.summary{grid-template-columns:1fr}.field{width:100%}}
</style>
</head>
<body>
<header class="nav">
<div class="brand"><div class="logo">ATC</div><div><h1>Anand Transport Company</h1><small>Reliable • Fast • Nationwide</small></div></div>
<a href="{{ url_for('admin') }}">← Admin Dashboard</a>
</header>
<main class="wrap">
<h2>Booking Report</h2>
<p style="color:#6b7280">Selected date period ki complete booking details.</p>
<form class="filter" method="GET">
<div class="row">
<div class="field"><label>From Date</label><input type="date" name="from_date" value="{{ from_date }}"></div>
<div class="field"><label>To Date</label><input type="date" name="to_date" value="{{ to_date }}"></div>
<button class="btn primary" type="submit">Generate Report</button>
<a class="btn secondary" href="{{ url_for('booking_report') }}">Reset</a>
</div>
</form>
<section class="summary">
<div class="stat"><div class="label">Total Docket</div><div class="num">{{ total_dockets }}</div></div>
<div class="stat"><div class="label">Total PKG</div><div class="num">{{ total_packages }}</div></div>
<div class="stat"><div class="label">Total Weight</div><div class="num">{{ total_weight_text }} KG</div></div>
<div class="stat"><div class="label">Total Amount</div><div class="num">₹ {{ total_amount_text }}</div></div>
</section>
<section class="card">
<div class="head"><strong>Booking Details</strong><span style="font-size:12px;color:#6b7280">{{ from_date or 'Beginning' }} → {{ to_date or 'Today' }}</span></div>
<div class="tablewrap"><table class="table">
<thead><tr><th>SR. No.</th><th>Docket No.</th><th>Consignor</th><th>Consignee</th><th>Date</th><th>Booking Basis</th><th>PKG</th><th>Weight</th><th>Delivery Location</th><th style="text-align:right">Amount</th></tr></thead>
<tbody>
{% for s in shipments %}
<tr><td class="center">{{ loop.index }}</td><td><strong>{{ s.docket }}</strong></td><td>{{ s.consignor or '-' }}</td><td>{{ s.consignee or '-' }}</td><td>{{ s.booking_date }}</td>
<td>{% set basis=(s.freight_basis or 'To Pay') %}{% if basis|lower == 'paid' %}<span class="badge paid">PAID</span>{% elif basis|lower == 'tbb' %}<span class="badge tbb">TBB</span>{% else %}<span class="badge topay">TO PAY</span>{% endif %}</td>
<td class="center">{{ s.packages or 0 }}</td><td>{{ s.weight or '-' }}</td><td><strong>{{ s.destination or '-' }}</strong></td><td class="amount">₹ {{ s.amount or '0' }}</td></tr>
{% else %}<tr><td colspan="10" style="text-align:center;padding:40px;color:#777">No bookings found for selected period.</td></tr>{% endfor %}
{% if shipments %}<tr class="total"><td colspan="6">TOTAL</td><td class="center">{{ total_packages }}</td><td>{{ total_weight_text }} KG</td><td>{{ total_dockets }} Docket</td><td class="amount">₹ {{ total_amount_text }}</td></tr>{% endif %}
</tbody></table></div>
</section>
</main>
</body>
</html>
"""


@app.route("/admin/booking-report")
@login_required
def booking_report():
    from_date = request.args.get("from_date", "").strip()
    to_date = request.args.get("to_date", "").strip()

    con = db()
    cur = con.cursor()

    conditions = []
    params = []
    if from_date:
        conditions.append("DATE(booking_date) >= %s")
        params.append(from_date)
    if to_date:
        conditions.append("DATE(booking_date) <= %s")
        params.append(to_date)

    where_sql = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    cur.execute(
        f"""
        SELECT id,docket,booking_date,source,destination,consignor,consignee,
               packages,weight,amount,freight_basis
        FROM shipments
        {where_sql}
        ORDER BY DATE(booking_date) ASC,id ASC
        """,
        params
    )
    shipments = cur.fetchall()

    cur.execute(
        f"""
        SELECT COUNT(*) AS total_dockets,
               COALESCE(SUM(packages),0) AS total_packages,
               COALESCE(SUM(COALESCE(NULLIF(regexp_replace(weight::text,'[^0-9.]','','g'),'')::NUMERIC,0)),0) AS total_weight,
               COALESCE(SUM(COALESCE(NULLIF(regexp_replace(amount::text,'[^0-9.]','','g'),'')::NUMERIC,0)),0) AS total_amount
        FROM shipments
        {where_sql}
        """,
        params
    )
    totals = cur.fetchone()

    cur.close()
    con.close()

    return render_template_string(
        BOOKING_REPORT_HTML,
        shipments=shipments,
        from_date=from_date,
        to_date=to_date,
        total_dockets=totals["total_dockets"] or 0,
        total_packages=totals["total_packages"] or 0,
        total_weight_text=money_text(totals["total_weight"] or 0),
        total_amount_text=money_text(totals["total_amount"] or 0)
    )



# =========================================================
# TBB CUSTOMER REPORT
# =========================================================

TBB_CUSTOMER_HTML = r'''
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TBB Customer Report - Anand Transport</title>
<style>
body{margin:0;font-family:Arial,Helvetica,sans-serif;background:#f5f7fb;color:#172033}
.wrap{max-width:1500px;margin:auto;padding:28px 4% 50px}
.nav{background:#fff;border-bottom:3px solid #f0a900;min-height:70px;display:flex;align-items:center;justify-content:space-between;padding:12px 4%;gap:20px}
.brand{display:flex;align-items:center;gap:12px}.logo{width:52px;height:52px;border-radius:12px;background:linear-gradient(135deg,#e51b00,#ffb000);display:grid;place-items:center;color:#fff;font-weight:900}
.brand h1{font-size:21px;margin:0;color:#b00000}.brand small{color:#555}.nav a{color:#111;text-decoration:none;font-weight:800;font-size:13px}
.wrap h2{margin-bottom:5px}.muted{color:#6b7280}
.filter,.card,.stat{background:#fff;border:1px solid #e6e8ef;border-radius:14px;box-shadow:0 3px 12px #00000008}
.filter{padding:18px;margin:20px 0}.row{display:flex;gap:12px;align-items:end;flex-wrap:wrap}.field{min-width:250px}
.field label{display:block;font-size:12px;font-weight:800;color:#6b7280;margin-bottom:6px;text-transform:uppercase}
.field input{width:100%;padding:10px 12px;border:1px solid #d8dce5;border-radius:8px;font-size:14px}
.btn{display:inline-flex;align-items:center;justify-content:center;text-decoration:none;border:0;border-radius:9px;padding:11px 15px;font-weight:800;cursor:pointer;min-height:42px}
.primary{background:#b40000;color:#fff}.secondary{background:#fff;color:#172033;border:1px solid #e6e8ef}
.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:20px}.stat{padding:17px}
.label{color:#6b7280;font-size:12px;font-weight:800;text-transform:uppercase}.num{font-size:25px;font-weight:900;margin-top:7px}
.card{overflow:hidden}.head{padding:17px 20px;border-bottom:1px solid #e6e8ef;display:flex;justify-content:space-between}
.tablewrap{overflow:auto}.table{width:100%;border-collapse:collapse;min-width:1400px}.table th,.table td{padding:12px 10px;border-bottom:1px solid #e6e8ef;font-size:13px;text-align:left}
.table th{background:#fafafa;color:#596174;font-size:11px;text-transform:uppercase;white-space:nowrap}.center{text-align:center!important}.amount{text-align:right!important;font-weight:800}
.total td{background:#fff8e8;border-top:2px solid #f0a900;font-weight:900}
@media(max-width:900px){.summary{grid-template-columns:repeat(2,1fr)}}@media(max-width:560px){.summary{grid-template-columns:1fr}.field{width:100%}}
</style>
</head>
<body>
<header class="nav">
<div class="brand"><div class="logo">ATC</div><div><h1>Anand Transport Company</h1><small>Reliable • Fast • Nationwide</small></div></div>
<a href="{{ url_for('admin') }}">← Admin Dashboard</a>
</header>
<main class="wrap">
<h2>TBB Customer</h2>
<p class="muted">Unique TBB Customer Code se sirf us customer ki saari TBB bookings dekhein.</p>
<form class="filter" method="GET">
<div class="row">
<div class="field"><label>TBB Customer Code</label><input name="code" value="{{ code }}" placeholder="e.g. TBB001" autocomplete="off"></div>
<button class="btn primary" type="submit">Search Customer</button>
<a class="btn secondary" href="{{ url_for('tbb_customer_report') }}">Reset</a>
</div>
</form>
{% if code %}
<section class="summary">
<div class="stat"><div class="label">TBB Docket</div><div class="num">{{ total_dockets }}</div></div>
<div class="stat"><div class="label">Total PKG</div><div class="num">{{ total_packages }}</div></div>
<div class="stat"><div class="label">Total Weight</div><div class="num">{{ total_weight_text }} KG</div></div>
<div class="stat"><div class="label">TBB Amount</div><div class="num">₹ {{ total_amount_text }}</div></div>
</section>
<section class="card">
<div class="head"><strong>TBB Booking Details</strong><span class="muted" style="font-size:12px">Code: {{ code }}</span></div>
<div class="tablewrap"><table class="table">
<thead><tr><th>SR. No.</th><th>Docket No.</th><th>Consignor</th><th>Consignee</th><th>Date</th><th>TBB Code</th><th>PKG</th><th>Weight</th><th>Delivery Location</th><th>Shipment Value</th><th>Amount</th></tr></thead>
<tbody>
{% for s in shipments %}
<tr><td class="center">{{ loop.index }}</td><td><strong>{{ s.docket }}</strong></td><td>{{ s.consignor or '-' }}</td><td>{{ s.consignee or '-' }}</td><td>{{ s.booking_date }}</td><td><strong>{{ s.tbb_customer_code }}</strong></td><td class="center">{{ s.packages or 0 }}</td><td>{{ s.weight or '-' }}</td><td><strong>{{ s.destination or '-' }}</strong></td><td class="amount">₹ {{ money_text(s.shipment_value) }}</td><td class="amount">₹ {{ money_text(s.amount) }}</td></tr>
{% else %}<tr><td colspan="11" style="text-align:center;padding:40px;color:#777">No TBB bookings found for this code.</td></tr>{% endfor %}
{% if shipments %}<tr class="total"><td colspan="6">TOTAL</td><td class="center">{{ total_packages }}</td><td>{{ total_weight_text }} KG</td><td>{{ total_dockets }} Docket</td><td>-</td><td class="amount">₹ {{ total_amount_text }}</td></tr>{% endif %}
</tbody></table></div>
</section>
{% endif %}
</main>
</body>
</html>
'''



# =========================================================
# TBB CUSTOMER MANAGEMENT
# =========================================================
TBB_PAGE_HTML = r"""
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TBB Customer - Anand Transport</title>
<style>*{box-sizing:border-box}body{margin:0;background:#f6f7fb;font-family:Arial;color:#172033}.top{background:#fff;border-bottom:3px solid #f0a900;padding:14px 4%;display:flex;justify-content:space-between;align-items:center;gap:15px;flex-wrap:wrap}.top a{font-weight:800;text-decoration:none;color:#222}.wrap{max-width:1500px;margin:auto;padding:25px 4%}.brand{font-weight:900;color:#b00000}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.card{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:20px;margin-bottom:18px;box-shadow:0 3px 12px #00000008}.field label{display:block;font-size:13px;font-weight:800;margin-bottom:6px}.field input{width:100%;padding:11px;border:1px solid #d5d9e1;border-radius:8px}.full{grid-column:1/-1}.btn{border:0;border-radius:9px;padding:11px 16px;background:#b40000;color:#fff;font-weight:900;cursor:pointer;text-decoration:none;display:inline-block}.btn2{background:#fff;color:#222;border:1px solid #ddd}.search{display:flex;gap:10px;flex-wrap:wrap}.search input{flex:1;min-width:220px;padding:11px;border:1px solid #d5d9e1;border-radius:8px}table{width:100%;border-collapse:collapse;min-width:1050px}th,td{padding:10px;border-bottom:1px solid #eee;text-align:left;font-size:13px;white-space:nowrap}th{background:#fafafa;font-size:11px;text-transform:uppercase;color:#687083}.table{overflow:auto}.detail{background:#fffaf0;border:1px solid #eadfca;border-radius:12px;padding:15px}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.stat{padding:14px;border:1px solid #eee;border-radius:10px;background:#fff}.stat b{font-size:25px}@media(max-width:750px){.grid,.stats{grid-template-columns:1fr}}
</style></head><body><header class="top"><div><div class="brand">ATC • Anand Transport Company</div><small>TBB Customer Management</small></div><div><a href="{{ url_for('admin') }}">← Dashboard</a></div></header><main class="wrap"><div class="card"><h2>Add TBB Customer</h2><form method="post" action="{{ url_for('tbb_customer_add') }}" enctype="multipart/form-data"><div class="grid"><div class="field"><label>Customer Name</label><input name="customer_name" required></div><div class="field"><label>Mobile No.</label><input name="mobile"></div><div class="field"><label>GSTIN No.</label><input name="gstin"></div><div class="field"><label>Address</label><input name="address"></div><div class="field"><label>Aadhaar No.</label><input name="aadhaar_no"></div><div class="field"><label>PAN No.</label><input name="pan_no"></div><div class="field"><label>Upload Aadhaar</label><input type="file" name="aadhaar_file" accept="image/*,.pdf"></div><div class="field"><label>Upload PAN</label><input type="file" name="pan_file" accept="image/*,.pdf"></div></div><p><button class="btn" type="submit">Generate Code & Save Customer</button></p></form></div>
<div class="card"><h2>Search Customer</h2><form class="search" method="get"><input name="q" value="{{ q }}" placeholder="Customer name or TBB code"><button class="btn" type="submit">Search</button><a class="btn btn2" href="{{ url_for('tbb_customers') }}">Clear</a><a class="btn" href="{{ url_for('tbb_report_pdf') }}?q={{ q|urlencode }}">Generate Report</a></form></div>
{% if selected %}<div class="card"><h2>{{ selected.customer_name }} <small>({{ selected.code }})</small></h2><div class="detail"><div><b>Mobile:</b> {{ selected.mobile or '-' }} &nbsp; <b>GSTIN:</b> {{ selected.gstin or '-' }}</div><div><b>Address:</b> {{ selected.address or '-' }}</div><div><b>Aadhaar:</b> {{ selected.aadhaar_no or '-' }} {% if selected.aadhaar_filename %}<a href="{{ url_for('tbb_doc',cid=selected.id,kind='aadhaar') }}">View</a>{% endif %} &nbsp; <b>PAN:</b> {{ selected.pan_no or '-' }} {% if selected.pan_filename %}<a href="{{ url_for('tbb_doc',cid=selected.id,kind='pan') }}">View</a>{% endif %}</div></div><div class="stats" style="margin-top:14px"><div class="stat"><small>Booked</small><br><b>{{ stats.booked }}</b></div><div class="stat"><small>Charges Added / Approved</small><br><b>{{ stats.approved }}</b></div><div class="stat"><small>Pending Charges</small><br><b>{{ stats.pending }}</b></div></div></div><div class="card"><h3>Customer Bookings</h3><div class="table"><table><thead><tr><th>Sr.</th><th>GR No.</th><th>Booking Date</th><th>Consignee</th><th>Delivery Location</th><th>Charge Weight</th><th>Actual Weight</th><th>Packages</th><th>Status</th><th>GR</th><th>Charges</th></tr></thead><tbody>{% for s in bookings %}<tr><td>{{ loop.index }}</td><td>{{ s.docket }}</td><td>{{ s.booking_date }}</td><td>{{ s.consignee or '-' }}</td><td>{{ s.destination }}</td><td>{{ s.charge_weight or s.weight or '-' }}</td><td>{{ s.actual_weight or '-' }}</td><td>{{ s.packages or 0 }}</td><td>{{ s.status }}</td><td><a href="{{ url_for('shipment_pdf',sid=s.id) }}" target="_blank">Download GR</a></td><td>{% if s.freight_basis == 'TBB' and not s.charges_approved %}<a href="{{ url_for('tbb_add_charges',sid=s.id) }}">Add Charges</a>{% else %}Approved{% endif %}</td></tr>{% endfor %}</tbody></table></div></div>{% endif %}
</main></body></html>
"""

@app.route('/admin/tbb-customers')
@login_required
def tbb_customers():
    q=request.args.get('q','').strip(); selected=None; bookings=[]; stats={'booked':0,'approved':0,'pending':0}
    con=db(); cur=con.cursor()
    if q:
        cur.execute("SELECT * FROM tbb_customers WHERE UPPER(code)=UPPER(%s) OR customer_name ILIKE %s ORDER BY id DESC LIMIT 1",(q,'%'+q+'%'))
        selected=cur.fetchone()
        if selected:
            cur.execute("SELECT * FROM shipments WHERE UPPER(COALESCE(tbb_customer_code,''))=UPPER(%s) ORDER BY DATE(booking_date) ASC,id ASC",(selected['code'],)); bookings=cur.fetchall()
            stats['booked']=len(bookings); stats['approved']=sum(1 for x in bookings if x.get('charges_approved')); stats['pending']=stats['booked']-stats['approved']
    cur.close(); con.close()
    return render_template_string(TBB_PAGE_HTML,q=q,selected=selected,bookings=bookings,stats=stats)

@app.route('/admin/tbb-customer/add',methods=['POST'])
@login_required
def tbb_customer_add():
    data=request.form; name=data.get('customer_name','').strip()
    if not name: flash('Customer name is required.'); return redirect(url_for('tbb_customers'))
    con=db(); cur=con.cursor(); now=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cur.execute("SELECT COALESCE(MAX(id),0)+1 AS n FROM tbb_customers"); n=cur.fetchone()['n']; code=f'TBB{int(n):04d}'
    af=request.files.get('aadhaar_file'); pf=request.files.get('pan_file')
    cur.execute("INSERT INTO tbb_customers(code,customer_name,mobile,gstin,address,aadhaar_no,pan_no,aadhaar_filename,aadhaar_data,pan_filename,pan_data,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (code,name,data.get('mobile','').strip(),data.get('gstin','').strip(),data.get('address','').strip(),data.get('aadhaar_no','').strip(),data.get('pan_no','').strip(),af.filename if af and af.filename else None,psycopg2.Binary(af.read()) if af and af.filename else None,pf.filename if pf and pf.filename else None,psycopg2.Binary(pf.read()) if pf and pf.filename else None,now,now)); con.commit(); cur.close(); con.close(); flash(f'TBB Customer created: {code}'); return redirect(url_for('tbb_customers')+'?q='+code)

@app.route('/admin/api/tbb-customer/<code>')
@login_required
def tbb_customer_api(code):
    con=db(); cur=con.cursor(); cur.execute("SELECT code,customer_name,mobile,gstin,address FROM tbb_customers WHERE UPPER(code)=UPPER(%s)",(code,)); c=cur.fetchone(); cur.close(); con.close(); return jsonify({'ok':bool(c),'customer':dict(c) if c else None})

@app.route('/api/tbb-customer/<code>')
def public_tbb_customer_api(code):
    con=db(); cur=con.cursor()
    cur.execute("SELECT code,customer_name,mobile,gstin,address FROM tbb_customers WHERE UPPER(code)=UPPER(%s)", (code,))
    c=cur.fetchone(); cur.close(); con.close()
    return jsonify({'found': bool(c), 'customer': dict(c) if c else None})


@app.route('/admin/tbb-document/<int:cid>/<kind>')
@login_required
def tbb_doc(cid,kind):
    col='aadhaar_data' if kind=='aadhaar' else 'pan_data'; namecol='aadhaar_filename' if kind=='aadhaar' else 'pan_filename'
    con=db(); cur=con.cursor(); cur.execute(f"SELECT {col},{namecol} FROM tbb_customers WHERE id=%s",(cid,)); r=cur.fetchone(); cur.close(); con.close()
    if not r or not r[col]: return 'Document not found',404
    return send_file(BytesIO(bytes(r[col])),download_name=r[namecol] or f'{kind}.bin',as_attachment=False)

@app.route('/admin/tbb/<int:sid>/charges',methods=['GET','POST'])
@login_required
def tbb_add_charges(sid):
    con=db(); cur=con.cursor(); cur.execute("SELECT * FROM shipments WHERE id=%s",(sid,)); s=cur.fetchone()
    if not s: cur.close(); con.close(); return 'Not found',404
    if request.method=='POST':
        d=request.form; f=money_value(d.get('freight_charge')); h=money_value(d.get('handling_charge')); dd=money_value(d.get('dd_charge')); o=money_value(d.get('other_charge')); total=f+h+dd+o; gst=total*0.18; grand=total+gst
        cur.execute("UPDATE shipments SET freight_charge=%s,handling_charge=%s,dd_charge=%s,other_charge=%s,charge_total=%s,gst_amount=%s,grand_total=%s,amount=%s,charges_approved=TRUE,updated_at=%s WHERE id=%s",(f,h,dd,o,total,gst,grand,grand,datetime.now().strftime('%Y-%m-%d %H:%M:%S'),sid)); con.commit(); cur.close(); con.close(); flash('TBB charges added/approved successfully.'); return redirect(url_for('tbb_customers')+'?q='+str(s.get('tbb_customer_code') or ''))
    cur.close(); con.close()
    return render_template_string("""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Add TBB Charges</title><style>body{font-family:Arial;background:#f6f7fb;padding:30px}.box{max-width:650px;margin:auto;background:#fff;padding:25px;border-radius:14px}label{display:block;font-weight:bold;margin-top:12px}input{width:100%;padding:11px;box-sizing:border-box;margin-top:5px;border:1px solid #ddd;border-radius:8px}button{margin-top:18px;padding:12px 18px;background:#b40000;color:#fff;border:0;border-radius:8px;font-weight:bold}</style></head><body><div class="box"><h2>Add Charges - {{ s.docket }}</h2><p>{{ s.consignor }} / {{ s.tbb_customer_code }}</p><form method="post">{% for n in ['freight_charge','handling_charge','dd_charge','other_charge'] %}<label>{{ n.replace('_',' ').title() }} (₹)</label><input name="{{n}}" value="{{ s[n] or 0 }}">{% endfor %}<button>Save & Approve Charges</button></form></div>,</body></html>""",s=s)

@app.route('/admin/tbb-report.pdf')
@login_required
def tbb_report_pdf():
    q=request.args.get('q','').strip(); con=db(); cur=con.cursor(); cur.execute("SELECT * FROM tbb_customers WHERE UPPER(code)=UPPER(%s) OR customer_name ILIKE %s ORDER BY id DESC LIMIT 1",(q,'%'+q+'%')); c=cur.fetchone()
    if not c: cur.close(); con.close(); return 'Customer not found',404
    cur.execute("SELECT * FROM shipments WHERE UPPER(COALESCE(tbb_customer_code,''))=UPPER(%s) AND charges_approved=TRUE ORDER BY DATE(booking_date) ASC,id ASC",(c['code'],)); rows=cur.fetchall(); cur.close(); con.close()
    buf=BytesIO(); doc=SimpleDocTemplate(buf,pagesize=A4,rightMargin=25,leftMargin=25,topMargin=30,bottomMargin=30); styles=getSampleStyleSheet(); story=[Paragraph(TRANSPORT_NAME,styles['Title']),Paragraph(TRANSPORT_ADDRESS,styles['Normal']),Paragraph('GSTIN: '+TRANSPORT_GST+' | '+TRANSPORT_HELPLINE,styles['Normal']),Spacer(1,12),Paragraph(f"TBB Customer Report — {c['customer_name']} ({c['code']})",styles['Heading2'])]
    data=[['Sr.','GR No.','Booking Date','Consignee','Destination','Packages','Charge Wt.','Actual Wt.','Status','Net Amount']]; net=0
    for i,r in enumerate(rows,1): net+=money_value(r.get('grand_total') or r.get('amount')); data.append([str(i),r['docket'],format_date_ddmmyyyy(r['booking_date']),r.get('consignee') or '-',r.get('destination') or '-',str(r.get('packages') or 0),r.get('charge_weight') or '-',r.get('actual_weight') or '-',r.get('status') or '-',money_text(r.get('grand_total') or r.get('amount'))])
    data.append(['','','','','','','','','NET AMOUNT',money_text(net)]); t=Table(data,repeatRows=1); t.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.4,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#fff3d6')),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('ALIGN',(-1,1),(-1,-1),'RIGHT'),('FONTSIZE',(0,0),(-1,-1),7)])); story += [t]; doc.build(story); buf.seek(0); return send_file(buf,download_name=f'TBB_Report_{c["code"]}.pdf',as_attachment=True,mimetype='application/pdf')

@app.route("/admin/tbb-customer")
@login_required
def tbb_customer_report():
    code = request.args.get("code", "").strip().upper()
    shipments = []
    totals = {"total_dockets":0,"total_packages":0,"total_weight":0,"total_amount":0}

    if code:
        con = db()
        cur = con.cursor()
        cur.execute(
            "SELECT id,docket,booking_date,source,destination,consignor,consignee,packages,weight,amount,freight_basis,shipment_value,tbb_customer_code "
            "FROM shipments "
            "WHERE freight_basis='TBB' AND UPPER(COALESCE(tbb_customer_code,''))=%s "
            "ORDER BY DATE(booking_date) ASC,id ASC",
            (code,)
        )
        shipments = cur.fetchall()
        cur.execute(
            "SELECT COUNT(*) AS total_dockets, "
            "COALESCE(SUM(packages),0) AS total_packages, "
            "COALESCE(SUM(COALESCE(NULLIF(regexp_replace(weight::text,'[^0-9.]','','g'),'')::NUMERIC,0)),0) AS total_weight, "
            "COALESCE(SUM(COALESCE(NULLIF(regexp_replace(amount::text,'[^0-9.]','','g'),'')::NUMERIC,0)),0) AS total_amount "
            "FROM shipments "
            "WHERE freight_basis='TBB' AND UPPER(COALESCE(tbb_customer_code,''))=%s",
            (code,)
        )
        totals = cur.fetchone()
        cur.close()
        con.close()

    return render_template_string(
        TBB_CUSTOMER_HTML,
        code=code,
        shipments=shipments,
        total_dockets=totals["total_dockets"] or 0,
        total_packages=totals["total_packages"] or 0,
        total_weight_text=money_text(totals["total_weight"] or 0),
        total_amount_text=money_text(totals["total_amount"] or 0),
        money_text=money_text
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

.report-filter{
background:white;
border:1px solid var(--line);
border-radius:14px;
padding:18px;
margin-bottom:22px;
box-shadow:0 3px 12px #00000008;
}
.report-filter-row{display:flex;gap:12px;align-items:end;flex-wrap:wrap}
.report-field{min-width:190px}
.report-field label{
display:block;font-size:12px;font-weight:800;color:var(--muted);
margin-bottom:6px;text-transform:uppercase;
}
.report-field input{
width:100%;padding:10px 12px;border:1px solid #d8dce5;
border-radius:8px;font-size:14px;
}
.report-summary{
display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:22px;
}
.report-card{
background:white;border:1px solid var(--line);border-radius:14px;
padding:17px;box-shadow:0 3px 12px #00000008;
}
.report-card .label{color:var(--muted);font-size:12px;font-weight:800;text-transform:uppercase}
.report-card .num{font-size:25px;font-weight:900;margin-top:7px}
.report-table{width:100%;border-collapse:collapse;min-width:1250px}
.report-table th,.report-table td{
padding:12px 10px;border-bottom:1px solid var(--line);
font-size:13px;text-align:left;vertical-align:middle;
}
.report-table th{
background:#fafafa;color:#596174;font-size:11px;text-transform:uppercase;white-space:nowrap;
}
.report-table .center{text-align:center}
.report-table .amount{text-align:right;font-weight:800}
.report-total td{background:#fff8e8;border-top:2px solid var(--gold);font-weight:900}
.basis-badge{
display:inline-block;padding:5px 9px;border-radius:999px;
font-size:11px;font-weight:900;white-space:nowrap;
}
.basis-paid{background:#e5f8ee;color:#08703c}
.basis-tbb{background:#fff4cf;color:#7b5200}
.basis-topay{background:#e7f1ff;color:#125a9c}
@media(max-width:900px){.report-summary{grid-template-columns:repeat(2,1fr)}}
@media(max-width:560px){.report-summary{grid-template-columns:1fr}.report-field{width:100%}}

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
href="{{ url_for('booking_report') }}"
>
📊 Booking Report
</a>

<a
class="btn secondary"
href="{{ url_for('tbb_customer_report') }}"
>
👤 TBB Customer
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
<h3>Booking Report Details</h3>
<div style="font-size:12px;color:var(--muted);font-weight:700">
{% if from_date or to_date %}{{ from_date or 'Beginning' }} → {{ to_date or 'Today' }}{% else %}All Bookings{% endif %}
</div>
</div>
<div class="tablewrap">
<table class="report-table">
<thead><tr>
<th>SR. No.</th><th>Docket No.</th><th>Consignor</th><th>Consignee</th>
<th>Date</th><th>Booking Basis</th><th>PKG</th><th>Weight</th>
<th>Delivery Location</th><th style="text-align:right">Amount</th>
</tr></thead>
<tbody>
{% for s in shipments %}
<tr>
<td class="center">{{ loop.index }}</td>
<td><strong>{{ s.docket }}</strong></td>
<td>{{ s.consignor or '-' }}</td>
<td>{{ s.consignee or '-' }}</td>
<td>{{ s.booking_date }}</td>
<td>
{% set basis=(s.freight_basis or 'To Pay') %}
{% if basis|lower == 'paid' %}
<span class="basis-badge basis-paid">PAID</span>
{% elif basis|lower == 'tbb' %}
<span class="basis-badge basis-tbb">TBB</span>
{% else %}
<span class="basis-badge basis-topay">TO PAY</span>
{% endif %}
</td>
<td class="center">{{ s.packages or 0 }}</td>
<td>{{ s.weight or '-' }}</td>
<td><strong>{{ s.destination or '-' }}</strong></td>
<td class="amount">₹ {{ s.amount or '0' }}</td>
</tr>
{% else %}
<tr><td colspan="10" style="text-align:center;padding:40px;color:#777">No bookings found for the selected period.</td></tr>
{% endfor %}
{% if shipments %}
<tr class="report-total">
<td colspan="6">TOTAL</td>
<td class="center">{{ total_packages }}</td>
<td>{{ total_weight_text }} KG</td>
<td>{{ total }} Docket</td>
<td class="amount">₹ {{ total_amount_text }}</td>
</tr>
{% endif %}
</tbody>
</table>
</div>
</section>

<section class="card">
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

ADMIN_PAGE_HTML = r"""
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin Panel - Anand Transport</title>
<style>
*{box-sizing:border-box}body{margin:0;font-family:Arial,Helvetica,sans-serif;background:#f6f7fb;color:#172033}.top{background:#fff;border-bottom:3px solid #f0a900;padding:14px 4%;display:flex;justify-content:space-between;align-items:center;gap:15px}.brand{display:flex;align-items:center;gap:12px}.logo{width:50px;height:50px;border-radius:12px;background:linear-gradient(135deg,#d40000,#ffb000);display:grid;place-items:center;color:#fff;font-weight:900}.brand h1{margin:0;color:#b00000;font-size:20px}.brand small{color:#666}.nav{display:flex;gap:8px;flex-wrap:wrap}.nav a{padding:10px 13px;border-radius:8px;text-decoration:none;color:#222;font-weight:800;font-size:13px}.nav a:hover{background:#fff3d6}.wrap{max-width:1500px;margin:auto;padding:25px 4% 50px}.head{display:flex;justify-content:space-between;align-items:center;gap:15px;flex-wrap:wrap}.head h2{margin:0}.btn{display:inline-block;padding:11px 16px;border-radius:9px;text-decoration:none;font-weight:900;background:#b40000;color:#fff}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:20px 0}.stat{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:18px;box-shadow:0 3px 12px #00000008}.stat b{font-size:28px}.label{color:#697386;font-size:13px;font-weight:700;margin-bottom:7px}.panel{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:18px;box-shadow:0 3px 12px #00000008;margin-bottom:18px}.actions{display:flex;gap:10px;flex-wrap:wrap}.action{flex:1;min-width:190px;border:1px solid #eadfca;background:#fffaf0;border-radius:12px;padding:15px;text-decoration:none;color:#222}.action strong{display:block;color:#9a0000;margin-bottom:5px}.tablewrap{overflow:auto}table{width:100%;border-collapse:collapse;min-width:1000px}th,td{padding:11px 9px;border-bottom:1px solid #eee;text-align:left;font-size:13px;white-space:nowrap}th{background:#fafafa;font-size:11px;text-transform:uppercase;color:#687083}.filters{display:flex;gap:10px;flex-wrap:wrap}.filters input{padding:10px;border:1px solid #d5d9e1;border-radius:8px}.muted{color:#6b7280}@media(max-width:900px){.cards{grid-template-columns:repeat(2,1fr)}}@media(max-width:560px){.cards{grid-template-columns:1fr}.top{align-items:flex-start;flex-direction:column}}
</style></head><body>
<header class="top"><div class="brand"><div class="logo">ATC</div><div><h1>Anand Transport Company</h1><small>Admin Panel • {{ username }}</small></div></div><nav class="nav"><a href="{{ url_for('admin') }}">Dashboard</a><a href="{{ url_for('booking_report') }}">Booking Report</a><a href="{{ url_for('new_shipment') }}">New Booking</a><a href="{{ url_for('tbb_customers') }}">TBB Customer</a><a href="{{ url_for('change_credentials') }}">Change Login</a><a href="{{ url_for('logout') }}">Logout</a></nav></header>
<main class="wrap"><div class="head"><div><h2>Admin Dashboard</h2><p class="muted">Booking summary and shipment management</p></div><a class="btn" href="{{ url_for('new_shipment') }}">+ New Booking</a></div>
<div class="cards"><div class="stat"><div class="label">Total Dockets</div><b>{{ total }}</b></div><div class="stat"><div class="label">Booked</div><b>{{ booked }}</b></div><div class="stat"><div class="label">In Transit</div><b>{{ in_transit }}</b></div><div class="stat"><div class="label">Delivered</div><b>{{ delivered }}</b></div></div>
<div class="panel"><div class="actions"><a class="action" href="{{ url_for('booking_report') }}"><strong>Booking Report</strong><span>Open detailed booking report separately.</span></a><a class="action" href="{{ url_for('tbb_customers') }}"><strong>TBB Customer</strong><span>Add, search, manage and generate customer reports.</span></a><a class="action" href="{{ url_for('new_shipment') }}"><strong>New Booking</strong><span>Create a new shipment with automatic totals.</span></a></div></div>
<div class="panel"><h3>Shipment Management</h3><div class="filters"><input id="search" placeholder="Search GR / consignor / consignee / status..."></div><div class="tablewrap"><table><thead><tr><th>Sr.</th><th>GR No.</th><th>Booking Date</th><th>Consignor</th><th>Consignee</th><th>Route</th><th>Charge Weight</th><th>Packages</th><th>Status</th><th>Action</th></tr></thead><tbody>{% for s in shipments %}<tr><td>{{ loop.index }}</td><td><b>{{ s.docket }}</b></td><td>{{ s.booking_date }}</td><td>{{ s.consignor or '-' }}</td><td>{{ s.consignee or '-' }}</td><td>{{ s.source }} → {{ s.destination }}</td><td>{{ s.charge_weight or s.weight or '-' }}</td><td>{{ s.packages or 0 }}</td><td>{{ s.status }}</td><td><a href="{{ url_for('edit_shipment',sid=s.id) }}">Edit</a> · <a href="{{ url_for('shipment_pdf',sid=s.id) }}" target="_blank">GR PDF</a></td></tr>{% endfor %}</tbody></table></div></div></main>
<script>document.getElementById('search').addEventListener('input',e=>{const q=e.target.value.toLowerCase();document.querySelectorAll('tbody tr').forEach(r=>r.style.display=r.innerText.toLowerCase().includes(q)?'':'none')})</script></body></html>
"""

@app.route("/admin")
@login_required
def admin():
    con=db(); cur=con.cursor()
    cur.execute("SELECT * FROM shipments ORDER BY DATE(booking_date) DESC,id DESC")
    shipments=cur.fetchall()
    cur.execute("SELECT COUNT(*) AS c FROM shipments"); total=cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM shipments WHERE status='Booked'"); booked=cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM shipments WHERE status='In Transit'"); in_transit=cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM shipments WHERE status='Delivered'"); delivered=cur.fetchone()["c"]
    cur.close(); con.close()
    return render_template_string(ADMIN_PAGE_HTML, shipments=shipments,total=total,booked=booked,in_transit=in_transit,delivered=delivered,username=session.get('admin_username','Admin'))

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

    consignor_gstin = data.get("consignor_gstin", "").strip()
    consignee_gstin = data.get("consignee_gstin", "").strip()
    invoice_ref = data.get("invoice_ref", "").strip()
    eway_bill_no = data.get("eway_bill_no", "").strip()
    actual_weight = data.get("actual_weight", "").strip()
    charge_weight = data.get("charge_weight", "").strip()
    freight_charge = data.get("freight_charge", "0").strip() or "0"
    handling_charge = data.get("handling_charge", "0").strip() or "0"
    dd_charge = data.get("dd_charge", "0").strip() or "0"
    other_charge = data.get("other_charge", "0").strip() or "0"
    charge_total = data.get("charge_total", "0").strip() or "0"
    gst_amount = data.get("gst_amount", "0").strip() or "0"
    grand_total = data.get("grand_total", "0").strip() or "0"
    amount = grand_total
    shipment_value = data.get(
        "shipment_value",
        ""
    ).strip()

    tbb_customer_code = data.get(
        "tbb_customer_code",
        ""
    ).strip().upper()

    freight_basis = data.get(
        "freight_basis",
        "To Pay"
    ).strip() or "To Pay"

    if freight_basis == "TBB" and not tbb_customer_code:
        flash("TBB Customer Code is required for TBB booking.")
        return redirect(url_for("new_shipment"))

    if freight_basis != "TBB":
        tbb_customer_code = ""

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

        if freight_basis == "TBB":
            cur.execute("SELECT customer_name,mobile,gstin,address FROM tbb_customers WHERE UPPER(code)=UPPER(%s)", (tbb_customer_code,))
            tbb_customer = cur.fetchone()
            if not tbb_customer:
                con.rollback()
                flash("TBB Customer Code not found. Please create/search the customer first.")
                return redirect(url_for("new_shipment"))
            # Always use the saved TBB customer details on the server.
            consignor = tbb_customer["customer_name"] or consignor
            consignor_contact = tbb_customer["mobile"] or consignor_contact
            consignor_gstin = tbb_customer["gstin"] or consignor_gstin
            consignor_address = tbb_customer["address"] or consignor_address

        # Keep legacy weight field populated so existing reports continue to work.
        weight = actual_weight or charge_weight or weight

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
                shipment_value,
                tbb_customer_code,
                goods_description,
                consignor_gstin,consignee_gstin,invoice_ref,eway_bill_no,actual_weight,charge_weight,
                freight_charge,handling_charge,dd_charge,other_charge,charge_total,gst_amount,grand_total,charges_approved
            )
            VALUES(
                %s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
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
                shipment_value,
                tbb_customer_code,
                goods_description,
                consignor_gstin,consignee_gstin,invoice_ref,eway_bill_no,actual_weight,charge_weight,
                freight_charge,handling_charge,dd_charge,other_charge,charge_total,gst_amount,grand_total,
                True if (freight_basis != "TBB" or money_value(grand_total) > 0) else False
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
<label>Expected Delivery Date</label>
<input type="date" name="expected_delivery">
</div>

<div class="field">
<label>Freight Basis</label>
<select name="freight_basis" id="freightBasis" required>
<option value="To Pay">To Pay</option><option value="Paid">Paid</option><option value="TBB">TBB</option>
</select>
</div>

<div class="field" id="tbbCodeField" style="display:none">
<label>TBB Code</label>
<input name="tbb_customer_code" id="tbbCustomerCode" placeholder="TBB001" autocomplete="off">
<div id="tbbHint" style="font-size:12px;color:#6b7280;margin-top:5px"></div>
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
<label>GSTIN No.</label><input name="consignor_gstin" id="consignorGstin">
</div>
<div class="field">
<label>Contact Number</label><input name="consignor_contact" id="consignorContact">
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


<div class="field"><label>GSTIN No.</label><input name="consignee_gstin"></div>
<div class="field"><label>Contact Number</label><input name="consignee_contact"></div>


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


<section class="card"><div class="ct">📦 Goods & Charges</div><div class="cb">
<div class="grid3">
<div class="field"><label>Packages</label><input type="number" min="1" name="packages" value="1" required></div>
<div class="field"><label>Actual Weight</label><input name="actual_weight" placeholder="e.g. 25 kg"></div>
<div class="field"><label>Charge Weight</label><input name="charge_weight" placeholder="e.g. 25 kg"></div>
<div class="field"><label>Invoice / Ref. No.</label><input name="invoice_ref"></div>
<div class="field"><label>E-Way Bill No.</label><input name="eway_bill_no" placeholder="Enter E-Way Bill No."></div>
<div class="field"><label>Shipment Value (₹)</label><input name="shipment_value"></div>
<div class="field"><label>Goods Description</label><input name="goods_description"></div>
<div class="field"><label>Freight (₹)</label><input class="charge" id="freightCharge" name="freight_charge" value="0" inputmode="decimal"></div>
<div class="field"><label>Handling (₹)</label><input class="charge" id="handlingCharge" name="handling_charge" value="0" inputmode="decimal"></div>
<div class="field"><label>DD Charge (₹)</label><input class="charge" id="ddCharge" name="dd_charge" value="0" inputmode="decimal"></div>
<div class="field"><label>Others (₹)</label><input class="charge" id="otherCharge" name="other_charge" value="0" inputmode="decimal"></div>
<div class="field"><label>Total (₹)</label><input id="chargeTotal" name="charge_total" value="0" readonly></div>
<div class="field"><label>GST Charge (₹) - Manual</label><input id="gstAmount" name="gst_amount" value="0" inputmode="decimal" placeholder="Enter GST amount manually"></div>
<div class="field"><label>Grand Total (₹)</label><input id="grandTotal" name="grand_total" value="0" readonly></div>
</div></div></section>

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

<script>
(function(){
 const basis=document.getElementById('freightBasis'), box=document.getElementById('tbbCodeField'), code=document.getElementById('tbbCustomerCode');
 function toggle(){const t=basis.value==='TBB';box.style.display=t?'':'none';code.required=t;if(!t){code.value='';document.getElementById('tbbHint').textContent='';}}
 basis.addEventListener('change',toggle); toggle();
 let timer; code.addEventListener('input',()=>{clearTimeout(timer);const c=code.value.trim();if(!c)return;timer=setTimeout(async()=>{try{const r=await fetch('/admin/api/tbb-customer/'+encodeURIComponent(c));const d=await r.json();if(d.ok){document.querySelector('[name=consignor]').value=d.customer.customer_name||'';document.getElementById('consignorContact').value=d.customer.mobile||'';document.getElementById('consignorGstin').value=d.customer.gstin||'';document.querySelector('[name=consignor_address]').value=d.customer.address||'';document.getElementById('tbbHint').textContent='Customer found: '+d.customer.customer_name;}else{document.getElementById('tbbHint').textContent='TBB code not found';}}catch(e){document.getElementById('tbbHint').textContent='Unable to lookup code';}},250);});
 const charges=['freightCharge','handlingCharge','ddCharge','otherCharge'].map(id=>document.getElementById(id));
 const gstInput=document.getElementById('gstAmount');
 function calc(){let total=charges.reduce((a,e)=>a+(parseFloat(e.value)||0),0);let gst=parseFloat(gstInput.value)||0;document.getElementById('chargeTotal').value=total.toFixed(2);document.getElementById('grandTotal').value=(total+gst).toFixed(2);}
 charges.forEach(e=>e.addEventListener('input',calc));
 gstInput.addEventListener('input',calc);
 calc();
})();
</script>

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

    consignor_gstin = data.get("consignor_gstin", old.get("consignor_gstin") or "").strip()
    consignee_gstin = data.get("consignee_gstin", old.get("consignee_gstin") or "").strip()
    invoice_ref = data.get("invoice_ref", old.get("invoice_ref") or "").strip()
    eway_bill_no = data.get("eway_bill_no", old.get("eway_bill_no") or "").strip()
    actual_weight = data.get("actual_weight", old.get("actual_weight") or "").strip()
    charge_weight = data.get("charge_weight", old.get("charge_weight") or "").strip()
    freight_charge = data.get("freight_charge", old.get("freight_charge") or "0").strip() or "0"
    handling_charge = data.get("handling_charge", old.get("handling_charge") or "0").strip() or "0"
    dd_charge = data.get("dd_charge", old.get("dd_charge") or "0").strip() or "0"
    other_charge = data.get("other_charge", old.get("other_charge") or "0").strip() or "0"
    charge_total = data.get("charge_total", old.get("charge_total") or "0").strip() or "0"
    gst_amount = data.get("gst_amount", old.get("gst_amount") or "0").strip() or "0"
    grand_total = data.get("grand_total", old.get("grand_total") or "0").strip() or "0"
    shipment_value = data.get("shipment_value", "").strip()
    freight_basis = data.get("freight_basis", old.get("freight_basis") or "To Pay").strip() or "To Pay"
    tbb_customer_code = data.get("tbb_customer_code", "").strip().upper()

    if freight_basis == "TBB" and not tbb_customer_code:
        flash("TBB Customer Code is required for TBB booking.")
        cur.close()
        con.close()
        return redirect(url_for("edit_shipment", sid=sid))

    if freight_basis != "TBB":
        tbb_customer_code = ""

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
            freight_basis=%s,
            shipment_value=%s,
            tbb_customer_code=%s,
            goods_description=%s,
            consignor_gstin=%s,
            consignee_gstin=%s,
            invoice_ref=%s,
            eway_bill_no=%s,
            actual_weight=%s,
            charge_weight=%s,
            freight_charge=%s,
            handling_charge=%s,
            dd_charge=%s,
            other_charge=%s,
            charge_total=%s,
            gst_amount=%s,
            grand_total=%s,
            amount=%s,
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
            freight_basis,
            shipment_value,
            tbb_customer_code,
            data.get("goods_description", old.get("goods_description") or "").strip(),
            consignor_gstin,consignee_gstin,invoice_ref,eway_bill_no,actual_weight,charge_weight,
            freight_charge,handling_charge,dd_charge,other_charge,charge_total,gst_amount,grand_total,grand_total,
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
