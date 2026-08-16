from flask import Flask, render_template, render_template_string, request, redirect, url_for, session, jsonify, flash, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
import os
import psycopg2
from psycopg2.extras import RealDictCursor


app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "CHANGE_THIS_SECRET_KEY_IN_PRODUCTION"
)

DATABASE_URL = os.environ.get("DATABASE_URL")

TRANSPORT_NAME = "ANAND TRANSPORT CARRIER"
TRANSPORT_GST = "08AOJPJ9966R1ZO"
TRANSPORT_ADDRESS = "Oppsite Mishreelal Girls Collage, Dedansar Road, Jaisalmer Raj. - 345001"
TRANSPORT_HELPLINE = "+91 7410823003"


def format_date_ddmmyyyy(value):
    """Convert stored dates to DD-MM-YYYY for display/PDF."""
    if not value:
        return "-"
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text[:10], fmt).strftime("%d-%m-%Y")
        except ValueError:
            pass
    return text


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

    # Add booking/PDF fields to existing databases without deleting old data.
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
            f"ALTER TABLE shipments ADD COLUMN IF NOT EXISTS {column} {sql_type}"
        )

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

    cur.execute("SELECT 1 FROM users LIMIT 1")
    if not cur.fetchone():
        cur.execute(
            """
            INSERT INTO users(username, password_hash)
            VALUES(%s,%s)
            """,
            ("admin", generate_password_hash("admin123"))
        )

    # Keep the existing demo shipment only when the database is empty.
    cur.execute("SELECT 1 FROM shipments LIMIT 1")
    if not cur.fetchone():
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            """
            INSERT INTO shipments
            (docket, booking_date, source, destination, consignor, consignee,
             packages, weight, status, location, expected_delivery, remark,
             created_at, updated_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (
                "AT100001", "2026-08-10", "Jaisalmer", "Jaipur",
                "ABC Industries", "XYZ Traders", 2, "35 kg",
                "In Transit", "Jodhpur", "2026-08-16",
                "Shipment reached Jodhpur hub.", now, now
            )
        )
        sid = cur.fetchone()["id"]
        demo_events = [
            ("Booked", "Jaisalmer", "Shipment booked.", "2026-08-10 10:20:00"),
            ("Picked Up", "Jaisalmer", "Shipment picked up.", "2026-08-10 14:30:00"),
            ("In Transit", "Jodhpur", "Shipment reached Jodhpur hub.", "2026-08-13 08:45:00")
        ]
        for status, location, remark, event_time in demo_events:
            cur.execute(
                """
                INSERT INTO tracking_events
                (shipment_id, status, location, remark, event_time)
                VALUES(%s,%s,%s,%s,%s)
                """,
                (sid, status, location, remark, event_time)
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
# CHANGE ADMIN USERNAME / PASSWORD
# =========================================================

@app.route("/admin/change-credentials", methods=["GET", "POST"])
def change_credentials():

    if request.method == "POST":

        current_username = request.form.get("current_username", "").strip()
        current_password = request.form.get("current_password", "")
        new_username = request.form.get("new_username", "").strip()
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not current_username or not new_username or not new_password:
            flash("Username and password are required.")
            return redirect(url_for("change_credentials"))

        if len(new_password) < 6:
            flash("New password must be at least 6 characters long.")
            return redirect(url_for("change_credentials"))

        if new_password != confirm_password:
            flash("New password and confirm password do not match.")
            return redirect(url_for("change_credentials"))

        con = db()
        cur = con.cursor()

        try:
            cur.execute(
                "SELECT * FROM users WHERE username=%s",
                (current_username,)
            )
            user = cur.fetchone()

            if not user or not check_password_hash(
                user["password_hash"],
                current_password
            ):
                flash("Current password is incorrect.")
                return redirect(url_for("change_credentials"))

            cur.execute(
                "SELECT id FROM users WHERE username=%s AND id<>%s",
                (new_username, user["id"])
            )

            if cur.fetchone():
                flash("This username is already in use.")
                return redirect(url_for("change_credentials"))

            cur.execute(
                """
                UPDATE users
                SET username=%s, password_hash=%s
                WHERE id=%s
                """,
                (
                    new_username,
                    generate_password_hash(new_password),
                    user["id"]
                )
            )

            con.commit()

            session["admin_username"] = new_username

            flash("Admin username and password changed successfully.")
            return redirect(url_for("admin"))

        except Exception:
            con.rollback()
            flash("Unable to change login details. Please try again.")
            return redirect(url_for("change_credentials"))

        finally:
            cur.close()
            con.close()

    return render_template_string(
        """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Change Admin Login</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    background: #f5f5f5;
                    margin: 0;
                    padding: 40px 20px;
                }
                .box {
                    max-width: 500px;
                    margin: auto;
                    background: white;
                    padding: 30px;
                    border-radius: 12px;
                    box-shadow: 0 2px 12px rgba(0,0,0,0.12);
                }
                h2 {
                    margin-top: 0;
                }
                label {
                    display: block;
                    margin-top: 15px;
                    margin-bottom: 6px;
                    font-weight: bold;
                }
                input {
                    width: 100%;
                    box-sizing: border-box;
                    padding: 11px;
                    border: 1px solid #ccc;
                    border-radius: 6px;
                    font-size: 15px;
                }
                button {
                    margin-top: 22px;
                    padding: 11px 18px;
                    border: none;
                    border-radius: 6px;
                    background: #c00;
                    color: white;
                    font-size: 15px;
                    cursor: pointer;
                }
                .back {
                    display: inline-block;
                    margin-left: 10px;
                    text-decoration: none;
                }
                .note {
                    color: #555;
                    font-size: 14px;
                }
            </style>
        </head>
        <body>
            <div class="box">
                <h2>Change Admin Login</h2>
                <p class="note">Enter your current password and choose a new username and password.</p>

                <form method="POST">
                    <label>Current Username</label>
                    <input type="text" name="current_username" value="{{ session.get('admin_username', '') }}" required>

                    <label>Current Password</label>
                    <input type="password" name="current_password" required>

                    <label>New Username</label>
                    <input type="text" name="new_username" value="{{ session.get('admin_username', '') }}" required>

                    <label>New Password</label>
                    <input type="password" name="new_password" minlength="6" required>

                    <label>Confirm New Password</label>
                    <input type="password" name="confirm_password" minlength="6" required>

                    <button type="submit">Save New Login Details</button>
                    <a class="back" href="{{ url_for('admin') }}">Back to Admin</a>
                </form>
            </div>
        </body>
        </html>
        """
    )



# =========================================================
# BOOKING / PDF HELPERS
# =========================================================

def generate_gr_no():
    con = db()
    cur = con.cursor()
    prefix = datetime.now().strftime("ATC-%Y%m%d")
    cur.execute(
        "SELECT COUNT(*) AS c FROM shipments WHERE docket LIKE %s",
        (prefix + "%",)
    )
    count = cur.fetchone()["c"] + 1
    cur.close()
    con.close()
    return f"{prefix}-{count:04d}"


def _pdf_paragraph(text, style):
    import html
    return Paragraph(html.escape(str(text or "")), style)


@app.route("/admin/shipment/<int:sid>/pdf")
@login_required
def shipment_pdf(sid):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT * FROM shipments WHERE id=%s", (sid,))
    shipment = cur.fetchone()
    cur.close()
    con.close()

    if not shipment:
        return "Shipment not found", 404

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=28, leftMargin=28,
        topMargin=24, bottomMargin=30
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("TitleATC2", parent=styles["Title"], fontSize=19, leading=22,
                           alignment=TA_CENTER, textColor=colors.HexColor("#b00000"), spaceAfter=3)
    center = ParagraphStyle("CenterATC2", parent=styles["Normal"], fontSize=8.5,
                            leading=11, alignment=TA_CENTER)
    heading = ParagraphStyle("HeadingATC2", parent=styles["Heading2"], fontSize=10.5,
                             leading=13, textColor=colors.HexColor("#b00000"), spaceBefore=5, spaceAfter=4)
    normal = ParagraphStyle("NormalATC2", parent=styles["Normal"], fontSize=8.7, leading=11)
    small = ParagraphStyle("SmallATC2", parent=styles["Normal"], fontSize=7.8, leading=9.5)
    terms = ParagraphStyle("TermsATC2", parent=styles["Normal"], fontSize=7.3, leading=9)
    right = ParagraphStyle("RightATC2", parent=normal, alignment=TA_RIGHT)

    booking_date = format_date_ddmmyyyy(shipment.get("booking_date"))
    expected_date = format_date_ddmmyyyy(shipment.get("expected_delivery"))
    freight_basis = shipment.get("freight_basis") or "To Pay"
    goods = shipment.get("goods_description") or "-"

    story = [
        Paragraph(TRANSPORT_NAME, title),
        Paragraph(f"GST ID: {TRANSPORT_GST} | Helpline: {TRANSPORT_HELPLINE}", center),
        Paragraph(TRANSPORT_ADDRESS, center),
        Spacer(1, 7),
        Paragraph("CONSIGNMENT / GR BOOKING RECEIPT", heading),
    ]

    info = [
        [_pdf_paragraph("GR / Consignment No.", normal), _pdf_paragraph(shipment["docket"], normal),
         _pdf_paragraph("Booking Date", normal), _pdf_paragraph(booking_date, normal)],
        [_pdf_paragraph("Expected Delivery", normal), _pdf_paragraph(expected_date, normal),
         _pdf_paragraph("Status", normal), _pdf_paragraph(shipment["status"], normal)],
        [_pdf_paragraph("From", normal), _pdf_paragraph(shipment["source"], normal),
         _pdf_paragraph("To", normal), _pdf_paragraph(shipment["destination"], normal)],
        [_pdf_paragraph("Packages", normal), _pdf_paragraph(shipment.get("packages"), normal),
         _pdf_paragraph("Weight", normal), _pdf_paragraph(shipment.get("weight") or "-", normal)],
        [_pdf_paragraph("Freight Basis", normal), _pdf_paragraph(freight_basis, normal),
         _pdf_paragraph("Amount", normal), _pdf_paragraph(shipment.get("amount") or "-", normal)],
    ]
    t = Table(info, colWidths=[100, 174, 92, 157])
    t.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#cccccc")),
        ("BACKGROUND", (0,0), (0,-1), colors.HexColor("#f7f7f7")),
        ("BACKGROUND", (2,0), (2,-1), colors.HexColor("#f7f7f7")),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 5), ("RIGHTPADDING", (0,0), (-1,-1), 5),
        ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    story.append(t)

    party = [
        [Paragraph("CONSIGNOR", heading), Paragraph("CONSIGNEE", heading)],
        [_pdf_paragraph(f"Name: {shipment.get('consignor') or '-'}", normal),
         _pdf_paragraph(f"Name: {shipment.get('consignee') or '-'}", normal)],
        [_pdf_paragraph(f"Address: {shipment.get('consignor_address') or '-'}", small),
         _pdf_paragraph(f"Address: {shipment.get('consignee_address') or '-'}", small)],
        [_pdf_paragraph(f"Contact: {shipment.get('consignor_contact') or '-'}", normal),
         _pdf_paragraph(f"Contact: {shipment.get('consignee_contact') or '-'}", normal)],
    ]
    pt = Table(party, colWidths=[262, 262])
    pt.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#cccccc")),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f7f7f7")),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 6), ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    story += [pt, Spacer(1, 7)]

    goods_table = Table([
        [Paragraph("GOODS DESCRIPTION", heading)],
        [_pdf_paragraph(goods, normal)]
    ], colWidths=[524])
    goods_table.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#cccccc")),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f7f7f7")),
        ("LEFTPADDING", (0,0), (-1,-1), 6), ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    story += [goods_table, Spacer(1, 7)]

    story += [
        Paragraph("REMARKS", heading),
        _pdf_paragraph(shipment.get("remark") or "-", normal),
        Spacer(1, 7),
        Paragraph("TERMS & CONDITIONS", heading),
    ]
    terms_text = (
        "1. Goods are accepted for transportation subject to applicable transport rules and conditions. "
        "2. Consignor is responsible for correct packing, description, quantity, weight and declaration of goods. "
        "3. Delivery is subject to route, service availability and receipt of necessary documents. "
        "4. Freight and other charges are payable according to the selected Freight Basis. "
        "5. Transit time is indicative and may vary due to operational, weather, traffic or other unavoidable reasons. "
        "6. Any shortage or damage should be reported at the time of delivery and acknowledged on the delivery record. "
        "7. The carrier shall not be responsible for prohibited, undeclared or improperly packed goods. "
        "8. This receipt should be retained by the customer for reference and delivery purposes."
    )
    terms_box = Table([[Paragraph(terms_text, terms)]], colWidths=[524])
    terms_box.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 0.5, colors.HexColor("#cccccc")),
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#fafafa")),
        ("LEFTPADDING", (0,0), (-1,-1), 7), ("RIGHTPADDING", (0,0), (-1,-1), 7),
        ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    story += [terms_box, Spacer(1, 14), Paragraph("For ANAND TRANSPORT CARRIER", right)]

    doc.build(story)
    buffer.seek(0)
    filename = f"{shipment['docket']}_GR.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")


ADMIN_DASHBOARD_HTML = r'''
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin Dashboard - Anand Transport</title>
<style>
:root{--red:#b40000;--red2:#d00000;--gold:#f0a900;--bg:#f5f7fb;--ink:#172033;--muted:#6b7280;--card:#fff;--line:#e6e8ef;--green:#14804a;--blue:#1769aa}
*{box-sizing:border-box}body{margin:0;font-family:Arial,Helvetica,sans-serif;background:var(--bg);color:var(--ink)}
.nav{background:#fff;border-bottom:3px solid var(--gold);height:78px;display:flex;align-items:center;justify-content:space-between;padding:0 4%;position:sticky;top:0;z-index:5}.brand{display:flex;align-items:center;gap:12px}.logo{width:52px;height:52px;border-radius:12px;background:linear-gradient(135deg,#e51b00,#ffb000);display:grid;place-items:center;color:#fff;font-weight:900;font-size:20px;box-shadow:0 3px 8px #bbb}.brand h1{font-size:21px;margin:0;color:#b00000}.brand small{display:block;margin-top:2px;color:#555}.navlinks{display:flex;gap:22px;align-items:center}.navlinks a{color:#161616;text-decoration:none;font-weight:700}.navlinks a:hover{color:var(--red)}
.wrap{max-width:1450px;margin:0 auto;padding:30px 4% 50px}.top{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:24px}.top h2{margin:0;font-size:28px}.top p{margin:7px 0 0;color:var(--muted)}.actions{display:flex;gap:10px;flex-wrap:wrap}.btn{display:inline-flex;align-items:center;gap:7px;text-decoration:none;border:0;border-radius:9px;padding:11px 15px;font-weight:800;cursor:pointer}.primary{background:var(--red);color:#fff}.secondary{background:#fff;color:var(--ink);border:1px solid var(--line)}.danger{background:#fff0f0;color:#a00000;border:1px solid #ffd0d0}.gold{background:#fff4cf;color:#7b5200;border:1px solid #f2d88c}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:22px}.stat{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px;box-shadow:0 3px 12px #00000008}.stat .label{color:var(--muted);font-size:13px;font-weight:700}.stat .num{font-size:29px;font-weight:900;margin-top:8px}.red{color:var(--red)}.blue{color:var(--blue)}.green{color:var(--green)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:0 3px 12px #00000008;overflow:hidden}.cardhead{padding:17px 20px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center}.cardhead h3{margin:0}.search{padding:9px 12px;border:1px solid #d8dce5;border-radius:8px;min-width:230px}.tablewrap{overflow:auto}table{width:100%;border-collapse:collapse;min-width:1050px}th,td{text-align:left;padding:13px 12px;border-bottom:1px solid var(--line);font-size:13px;vertical-align:top}th{background:#fafafa;color:#596174;font-size:12px;text-transform:uppercase}tr:hover td{background:#fcfcfd}.badge{display:inline-block;padding:5px 9px;border-radius:999px;font-size:11px;font-weight:800;background:#eee}.badge.booked{background:#fff0cf;color:#8a5a00}.badge.transit{background:#e7f1ff;color:#125a9c}.badge.delivered{background:#e5f8ee;color:#08703c}.actions-cell{display:flex;gap:6px;flex-wrap:wrap}.mini{padding:7px 9px;border-radius:7px;font-size:11px;font-weight:800;text-decoration:none;border:1px solid var(--line);background:#fff;color:#222}.mini.pdf{background:#fff4cf;color:#775000}.mini.edit{background:#e9f3ff;color:#14598f}.mini.delete{background:#fff0f0;color:#a00000}.empty{padding:40px;text-align:center;color:var(--muted)}
.footer{margin-top:30px;text-align:center;color:#777;font-size:12px}.flash{background:#e9f8ef;color:#126b3d;border:1px solid #bde8ce;border-radius:10px;padding:12px 15px;margin-bottom:18px;font-weight:700}
@media(max-width:900px){.stats{grid-template-columns:repeat(2,1fr)}.top{align-items:flex-start;flex-direction:column}.navlinks{gap:10px;font-size:12px}.brand h1{font-size:17px}}@media(max-width:560px){.stats{grid-template-columns:1fr}.nav{height:auto;padding:14px 4%;gap:12px;align-items:flex-start}.navlinks{flex-wrap:wrap}.wrap{padding-top:20px}}
</style></head><body>
<header class="nav"><div class="brand"><div class="logo">ATC</div><div><h1>Anand Transport Company</h1><small>Reliable • Fast • Nationwide</small></div></div><nav class="navlinks"><a href="/">Home</a><a href="/">Track Shipment</a><a href="/about">About Us</a><a href="{{ url_for('change_credentials') }}">Change Login</a><a href="{{ url_for('logout') }}">Logout</a></nav></header>
<main class="wrap"><div class="top"><div><h2>Admin Dashboard</h2><p>Welcome, {{ username }}. Manage bookings, shipments and tracking.</p></div><div class="actions"><a class="btn primary" href="{{ url_for('new_shipment') }}">＋ New Booking</a><a class="btn secondary" href="{{ url_for('admin') }}">↻ Refresh</a></div></div>
{% with messages=get_flashed_messages() %}{% if messages %}{% for m in messages %}<div class="flash">{{ m }}</div>{% endfor %}{% endif %}{% endwith %}
<section class="stats"><div class="stat"><div class="label">TOTAL SHIPMENTS</div><div class="num">{{ total }}</div></div><div class="stat"><div class="label">BOOKED</div><div class="num red">{{ booked }}</div></div><div class="stat"><div class="label">IN TRANSIT</div><div class="num blue">{{ in_transit }}</div></div><div class="stat"><div class="label">DELIVERED</div><div class="num green">{{ delivered }}</div></div></section>
<section class="card"><div class="cardhead"><h3>Shipment Management</h3><input class="search" id="search" placeholder="Search GR / route / name..."></div><div class="tablewrap"><table id="shipTable"><thead><tr><th>GR / Docket</th><th>Route</th><th>Consignor</th><th>Consignee</th><th>PKG</th><th>Weight</th><th>Amount</th><th>Status</th><th>Updated</th><th>Actions</th></tr></thead><tbody>{% for s in shipments %}<tr><td><strong>{{ s.docket }}</strong><br><small>{{ s.booking_date }}</small></td><td>{{ s.source }} → {{ s.destination }}<br><small>{{ s.location or '' }}</small></td><td>{{ s.consignor or '-' }}<br><small>{{ s.consignor_contact or '' }}</small></td><td>{{ s.consignee or '-' }}<br><small>{{ s.consignee_contact or '' }}</small></td><td>{{ s.packages }}</td><td>{{ s.weight or '-' }}</td><td>{{ s.amount or '-' }}</td><td>{% if s.status=='Booked' %}<span class="badge booked">Booked</span>{% elif s.status=='Delivered' %}<span class="badge delivered">Delivered</span>{% elif s.status=='In Transit' %}<span class="badge transit">In Transit</span>{% else %}<span class="badge">{{ s.status }}</span>{% endif %}</td><td>{{ s.updated_at }}</td><td><div class="actions-cell"><a class="mini pdf" href="{{ url_for('shipment_pdf', sid=s.id) }}">PDF</a><a class="mini edit" href="{{ url_for('edit_shipment', sid=s.id) }}">Edit</a><form method="POST" action="{{ url_for('delete_shipment', sid=s.id) }}" onsubmit="return confirm('Delete this shipment?')"><button class="mini delete" type="submit">Delete</button></form></div></td></tr>{% else %}<tr><td colspan="10" class="empty">No shipments found.</td></tr>{% endfor %}</tbody></table></div></section>
<div class="footer">ANAND TRANSPORT CARRIER • GST ID {{ transport_gst if transport_gst else '08AOJPJ9966R1ZO' }} • +91 7410823003</div></main>
<script>const q=document.getElementById('search');q.addEventListener('input',()=>{const v=q.value.toLowerCase();document.querySelectorAll('#shipTable tbody tr').forEach(r=>{r.style.display=r.innerText.toLowerCase().includes(v)?'':'none'})});</script></body></html>
'''

BOOKING_FORM_HTML = r'''
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>New Booking - Anand Transport</title>
<style>
:root{--red:#b40000;--gold:#f0a900;--bg:#f5f7fb;--ink:#172033;--muted:#687083;--line:#e1e5ec}*{box-sizing:border-box}body{margin:0;font-family:Arial,Helvetica,sans-serif;background:var(--bg);color:var(--ink)}.nav{height:78px;background:#fff;border-bottom:3px solid var(--gold);display:flex;justify-content:space-between;align-items:center;padding:0 4%}.brand{display:flex;align-items:center;gap:12px}.logo{width:52px;height:52px;border-radius:12px;background:linear-gradient(135deg,#e51b00,#ffb000);display:grid;place-items:center;color:#fff;font-weight:900}.brand h1{font-size:20px;color:#b00000;margin:0}.brand small{color:#555}.nav a{text-decoration:none;color:#111;font-weight:700}.wrap{max-width:1100px;margin:0 auto;padding:28px 4% 50px}.head{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px}.head h2{margin:0;font-size:27px}.head p{margin:6px 0;color:var(--muted)}.back{color:#222;text-decoration:none;font-weight:700}.card{background:#fff;border:1px solid var(--line);border-radius:15px;box-shadow:0 4px 18px #0000000b;margin-bottom:18px;overflow:hidden}.ct{padding:15px 20px;background:#fff8e8;border-bottom:1px solid #f1e0b4;color:#8a5600;font-weight:900}.cb{padding:20px}.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.field label{display:block;font-size:13px;font-weight:800;margin-bottom:6px}.field input,.field textarea,.field select{width:100%;border:1px solid #d5d9e1;border-radius:8px;padding:11px;font-size:14px;outline:none}.field input:focus,.field textarea:focus{border-color:#c00000;box-shadow:0 0 0 3px #c0000012}.field textarea{min-height:80px;resize:vertical}.full{grid-column:1/-1}.actions{display:flex;justify-content:flex-end;gap:10px;margin-top:10px}.btn{padding:12px 18px;border-radius:9px;font-weight:900;text-decoration:none;border:0;cursor:pointer}.primary{background:var(--red);color:#fff}.secondary{background:#fff;color:#222;border:1px solid var(--line)}.hint{font-size:12px;color:var(--muted);margin-top:5px}.notice{padding:13px 15px;background:#eef6ff;border:1px solid #cfe3fb;border-radius:10px;color:#155a8f;font-size:13px;font-weight:700;margin-bottom:18px}@media(max-width:700px){.grid,.grid3{grid-template-columns:1fr}.head{align-items:flex-start;gap:10px;flex-direction:column}.nav{height:auto;padding:12px 4%}.brand h1{font-size:16px}}
</style></head><body><header class="nav"><div class="brand"><div class="logo">ATC</div><div><h1>Anand Transport Company</h1><small>Reliable • Fast • Nationwide</small></div></div><a href="{{ url_for('admin') }}">← Admin Dashboard</a></header>
<main class="wrap"><div class="head"><div><h2>New Shipment Booking</h2><p>Create GR/Consignment and put it directly into customer tracking.</p></div></div><div class="notice">After booking, the shipment status will automatically be <strong>BOOKED</strong>. Customer can track it using the GR/Consignment number. PDF download is available only inside Admin Dashboard.</div>
<form method="POST"><section class="card"><div class="ct">📦 Booking Details</div><div class="cb"><div class="grid3"><div class="field"><label>Consignment / GR No.</label><input name="docket" value="{{ default_gr }}" required><div class="hint">You can replace the auto-generated number.</div></div><div class="field"><label>Booking Date</label><input type="date" name="booking_date" value="{{ today }}" required></div><div class="field"><label>Expected Delivery Date</label><input type="date" name="expected_delivery"></div></div></div></section>
<section class="card"><div class="ct">🚚 Route</div><div class="cb"><div class="grid"><div class="field"><label>From</label><input name="source" placeholder="Origin location" required></div><div class="field"><label>To</label><input name="destination" placeholder="Destination location" required></div></div></div></section>
<section class="card"><div class="ct">👤 Consignor</div><div class="cb"><div class="grid"><div class="field"><label>Consignor Name</label><input name="consignor" required></div><div class="field"><label>Contact Number</label><input name="consignor_contact"></div><div class="field full"><label>Address</label><textarea name="consignor_address"></textarea></div></div></div></section>
<section class="card"><div class="ct">👤 Consignee</div><div class="cb"><div class="grid"><div class="field"><label>Consignee Name</label><input name="consignee" required></div><div class="field"><label>Contact Number</label><input name="consignee_contact"></div><div class="field full"><label>Address</label><textarea name="consignee_address"></textarea></div></div></div></section>
<section class="card"><div class="ct">📦 Goods & Charges</div><div class="cb"><div class="grid3"><div class="field"><label>Packages</label><input type="number" min="1" name="packages" value="1" required></div><div class="field"><label>Weight (kg)</label><input name="weight" placeholder="e.g. 25 kg"></div><div class="field"><label>Amount (₹)</label><input name="amount" placeholder="e.g. 1250"></div></div><div class="grid" style="margin-top:16px"><div class="field"><label>Freight Basis</label><select name="freight_basis" required><option value="To Pay">To Pay</option><option value="Paid">Paid</option><option value="TBB">TBB</option></select></div><div class="field"><label>Goods Description</label><input name="goods_description" placeholder="e.g. Electrical Items, Spare Parts, Machinery"></div></div></div></section>
<section class="card"><div class="ct">📝 Remarks</div><div class="cb"><div class="grid"><div class="field"><label>Booking Time</label><input type="time" name="event_time"></div><div class="field"><label>Remark</label><input name="remark" placeholder="Optional remark"></div></div></div></section>
<div class="actions"><a class="btn secondary" href="{{ url_for('admin') }}">Cancel</a><button class="btn primary" type="submit">✓ Book Shipment</button></div></form></main></body></html>
'''

# =========================================================
# ADMIN DASHBOARD
# =========================================================

@app.route("/admin")
@login_required
def admin():

    con = db()
    cur = con.cursor()
    cur.execute("SELECT * FROM shipments ORDER BY updated_at DESC")
    shipments = cur.fetchall()

    cur.execute("SELECT COUNT(*) AS c FROM shipments")
    total = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM shipments WHERE status='Booked'")
    booked = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM shipments WHERE status='In Transit'")
    in_transit = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM shipments WHERE status='Delivered'")
    delivered = cur.fetchone()["c"]

    cur.close()
    con.close()

    return render_template_string(ADMIN_DASHBOARD_HTML,
                                  shipments=shipments,
                                  total=total,
                                  booked=booked,
                                  in_transit=in_transit,
                                  delivered=delivered,
                                  username=session.get("admin_username", "Admin"),
                                  transport_gst=TRANSPORT_GST)


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
        return render_template_string(BOOKING_FORM_HTML,
                                      today=datetime.now().strftime("%Y-%m-%d"),
                                      default_gr=generate_gr_no())

    data = request.form
    docket = data.get("docket", "").strip() or generate_gr_no()
    booking_date = data.get("booking_date", "").strip() or datetime.now().strftime("%Y-%m-%d")
    source = data.get("source", "").strip()
    destination = data.get("destination", "").strip()
    consignor = data.get("consignor", "").strip()
    consignor_address = data.get("consignor_address", "").strip()
    consignor_contact = data.get("consignor_contact", "").strip()
    consignee = data.get("consignee", "").strip()
    consignee_address = data.get("consignee_address", "").strip()
    consignee_contact = data.get("consignee_contact", "").strip()
    packages = int(data.get("packages") or 1)
    weight = data.get("weight", "").strip()
    amount = data.get("amount", "").strip()
    freight_basis = data.get("freight_basis", "To Pay").strip() or "To Pay"
    goods_description = data.get("goods_description", "").strip()
    expected_delivery = data.get("expected_delivery", "").strip()
    remark = data.get("remark", "").strip()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    event_time = data.get("event_time", "").strip() or datetime.now().strftime("%H:%M")
    manual_event_time = f"{booking_date} {event_time}:00"

    if not source or not destination or not consignor or not consignee:
        flash("Please fill From, To, Consignor and Consignee details.")
        return redirect(url_for("new_shipment"))

    con = db()
    cur = con.cursor()
    try:
        cur.execute(
            """
            INSERT INTO shipments
            (docket, booking_date, source, destination, consignor, consignee,
             packages, weight, status, location, expected_delivery, remark,
             created_at, updated_at, consignor_address, consignor_contact,
             consignee_address, consignee_contact, amount, freight_basis, goods_description)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (docket, booking_date, source, destination, consignor, consignee,
             packages, weight, "Booked", source, expected_delivery, remark,
             now, now, consignor_address, consignor_contact,
             consignee_address, consignee_contact, amount, freight_basis, goods_description)
        )
        sid = cur.fetchone()["id"]

        cur.execute(
            """
            INSERT INTO tracking_events
            (shipment_id, status, location, remark, event_time)
            VALUES(%s,%s,%s,%s,%s)
            """,
            (sid, "Booked", source, "Shipment booked.", manual_event_time)
        )
        con.commit()
        flash(f"Booking {docket} created successfully. You can download its PDF from the dashboard.")
    except psycopg2.IntegrityError:
        con.rollback()
        flash("GR / Consignment number already exists. Please use another number.")
    finally:
        cur.close()
        con.close()

    return redirect(url_for("admin"))


# =========================================================
# EDIT SHIPMENT
# =========================================================

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

    # -----------------------------------------------------
    # GET EXISTING SHIPMENT
    # -----------------------------------------------------

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
        return "Shipment not found", 404

    # =====================================================
    # GET REQUEST
    # =====================================================

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

    # =====================================================
    # POST REQUEST
    # =====================================================

    data = request.form

    # -----------------------------------------------------
    # BASIC SHIPMENT DATA
    # -----------------------------------------------------

    docket = data.get("docket", "").strip()

    booking_date = data.get(
        "booking_date",
        ""
    ).strip()

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

    consignor_contact = data.get(
        "consignor_contact",
        ""
    ).strip()

    consignor_address = data.get(
        "consignor_address",
        ""
    ).strip()

    consignee = data.get(
        "consignee",
        ""
    ).strip()

    consignee_contact = data.get(
        "consignee_contact",
        ""
    ).strip()

    consignee_address = data.get(
        "consignee_address",
        ""
    ).strip()

    packages = int(
        data.get("packages") or 1
    )

    weight = data.get(
        "weight",
        ""
    ).strip()

    # -----------------------------------------------------
    # CHARGES / GOODS
    # -----------------------------------------------------

    amount = data.get(
        "amount",
        ""
    ).strip()

    freight_basis = data.get(
        "freight_basis",
        "To Pay"
    ).strip()

    if freight_basis not in [
        "To Pay",
        "Paid",
        "TBB"
    ]:
        freight_basis = "To Pay"

    goods_description = data.get(
        "goods_description",
        ""
    ).strip()

    # -----------------------------------------------------
    # STATUS / LOCATION
    # -----------------------------------------------------

    status = data.get(
        "status",
        "Booked"
    ).strip()

    location = data.get(
        "location",
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

    # -----------------------------------------------------
    # EVENT DATE / TIME
    # -----------------------------------------------------

    event_date = data.get(
        "event_date",
        ""
    ).strip()

    event_time = data.get(
        "event_time",
        ""
    ).strip()

    if not event_date:
        event_date = booking_date

    if not event_time:
        event_time = "10:00"

    manual_event_time = (
        f"{event_date} {event_time}:00"
    )

    # -----------------------------------------------------
    # INTERNAL UPDATE TIME
    # -----------------------------------------------------

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # =====================================================
    # VALIDATION
    # =====================================================

    if not docket:
        flash("Docket / AWB number is required.")
        cur.close()
        con.close()
        return redirect(
            url_for(
                "edit_shipment",
                sid=sid
            )
        )

    if not booking_date:
        flash("Booking date is required.")
        cur.close()
        con.close()
        return redirect(
            url_for(
                "edit_shipment",
                sid=sid
            )
        )

    if not source or not destination:
        flash("From and To locations are required.")
        cur.close()
        con.close()
        return redirect(
            url_for(
                "edit_shipment",
                sid=sid
            )
        )

    # =====================================================
    # UPDATE SHIPMENT MASTER DATA
    # =====================================================

    try:

        cur.execute(
            """
            UPDATE shipments
            SET
                docket=%s,
                booking_date=%s,
                source=%s,
                destination=%s,

                consignor=%s,
                consignor_address=%s,
                consignor_contact=%s,

                consignee=%s,
                consignee_address=%s,
                consignee_contact=%s,

                packages=%s,
                weight=%s,

                status=%s,
                location=%s,
                expected_delivery=%s,
                remark=%s,

                amount=%s,
                freight_basis=%s,
                goods_description=%s,

                updated_at=%s

            WHERE id=%s
            """,
            (
                docket,
                booking_date,
                source,
                destination,

                consignor,
                consignor_address,
                consignor_contact,

                consignee,
                consignee_address,
                consignee_contact,

                packages,
                weight,

                status,
                location,
                expected_delivery,
                remark,

                amount,
                freight_basis,
                goods_description,

                now,
                sid
            )
        )

        # =================================================
        # FIND ORIGINAL BOOKED EVENT
        # =================================================

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

        # =================================================
        # REMOVE DUPLICATE BOOKED EVENTS
        # Keep only oldest Booked event.
        # =================================================

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

        # =================================================
        # IF CURRENT STATUS IS BOOKED
        # =================================================

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
                        source,
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
                        source,
                        "Shipment booked.",
                        manual_event_time
                    )
                )

        # =================================================
        # STATUS IS NOT BOOKED
        # =================================================

        else:

            # ---------------------------------------------
            # Find latest event of selected status
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
            # Create a NEW tracking event.
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
            # SAME STATUS
            # Update existing event.
            # Do not create duplicate.
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
            # No event exists for this status.
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

        # =================================================
        # SAVE EVERYTHING
        # =================================================

        con.commit()

        flash(
            "Shipment updated successfully."
        )

    except psycopg2.IntegrityError:

        con.rollback()

        flash(
            "Docket / AWB number already exists. "
            "Please use another number."
        )

    except Exception as e:

        con.rollback()

        print(
            "EDIT SHIPMENT ERROR:",
            str(e)
        )

        flash(
            "Unable to update shipment. Please try again."
        )

    finally:

        cur.close()
        con.close()

    return redirect(
        url_for("admin")
    )

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
