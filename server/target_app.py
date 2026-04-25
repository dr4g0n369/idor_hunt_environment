import os
import sqlite3

from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for, flash


DB_SEED_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    email TEXT,
    phone TEXT,
    department TEXT
);
CREATE TABLE IF NOT EXISTS tokens (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    product TEXT NOT NULL,
    amount REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    shipping_address TEXT
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    classification TEXT DEFAULT 'internal'
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY,
    created_by INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    visibility TEXT DEFAULT 'managers'
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO users VALUES
    (1, 'admin',    'admin',   'admin@corp.internal',    '+1-555-0100', 'IT'),
    (2, 'manager1', 'manager', 'manager1@corp.internal', '+1-555-0201', 'Engineering'),
    (3, 'alice',    'user',    'alice@corp.internal',    '+1-555-0301', 'Engineering'),
    (4, 'bob',      'user',    'bob@corp.internal',      '+1-555-0401', 'Sales'),
    (5, 'guest',    'guest',   'guest@corp.internal',     NULL,          'External');

INSERT OR IGNORE INTO tokens VALUES
    ('tok_admin_a8x', 1),
    ('tok_mgr_k9m',   2),
    ('tok_alice_j3p', 3),
    ('tok_bob_m2q',   4),
    ('tok_guest_q1r', 5);

INSERT OR IGNORE INTO orders VALUES
    (1, 3, 'Laptop Pro X1',       1299.99, 'shipped',    '123 Main St, Anytown'),
    (2, 3, 'USB-C Hub',             49.99, 'delivered',  '123 Main St, Anytown'),
    (3, 4, 'Monitor 4K UHD',       599.99, 'pending',    '456 Oak Ave, Springfield'),
    (4, 4, 'Mechanical Keyboard',  149.99, 'shipped',    '456 Oak Ave, Springfield'),
    (5, 1, 'Server Rack Unit',    8999.99, 'processing', '1 Corporate HQ, Metro City'),
    (6, 2, 'Standing Desk',        799.99, 'delivered',  '789 Pine Rd, Lakewood');

INSERT OR IGNORE INTO documents VALUES
    (1, 1, 'Security Policy v3',       'All employees must enable 2FA. VPN required for remote access. Password rotation every 90 days.', 'confidential'),
    (2, 2, 'Q4 Engineering Roadmap',   'Priority 1: Auth module rewrite. Priority 2: API rate limiting. Priority 3: Migrate to K8s.',     'internal'),
    (3, 3, 'Code Review Checklist',    'Check for SQL injection, XSS, CSRF. Validate all user inputs. Use parameterized queries.',         'internal'),
    (4, 4, 'Sales Playbook 2024',      'Key accounts: Acme Corp ($500K), Globex Inc ($320K), Initech ($180K). Renewal dates in Q1.',      'internal'),
    (5, 1, 'Incident Response Plan',   'Step 1: Isolate affected systems. Step 2: Notify CISO. Step 3: Preserve forensic evidence.',      'confidential');

INSERT OR IGNORE INTO reports VALUES
    (1, 2, 'Q3 Revenue Report',          'Total revenue: $4.2M vs target $3.8M. Key wins: Acme Corp deal ($500K). Pipeline: $2.1M for Q4.',                          'managers'),
    (2, 1, 'Security Audit 2024-Q2',     'Critical: SQL injection in /legacy/search. High: Missing rate limiting on /api/login. 2,340 records potentially exposed.',  'admin'),
    (3, 2, 'Team Performance Review',    'Alice Chen: Exceeds expectations - led auth module project. Bob Smith: Meets expectations - solid Q3 numbers.',              'managers');

INSERT OR IGNORE INTO settings VALUES
    ('db_connection',   'postgresql://dbadmin:Pr0d_S3cret!@10.0.1.5:5432/production'),
    ('stripe_api_key',  'sk_test_FAKE_4eC39HqLyjWDarjtT1zdp7dc'),
    ('jwt_secret',      'xK8#mP9$qR2&nL5@vT7!'),
    ('smtp_credentials','notifications@corp.internal:M4ilP@ss!2024'),
    ('aws_secret_key',  'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY');

CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY,
    author_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    published_at TEXT NOT NULL,
    pinned INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS shared_files (
    id INTEGER PRIMARY KEY,
    uploaded_by INTEGER NOT NULL,
    filename TEXT NOT NULL,
    description TEXT NOT NULL,
    shared_with TEXT NOT NULL DEFAULT 'everyone',
    uploaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS catalog (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    price REAL NOT NULL,
    category TEXT NOT NULL,
    in_stock INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY,
    created_by INTEGER NOT NULL,
    subject TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    priority TEXT NOT NULL DEFAULT 'medium',
    is_public INTEGER DEFAULT 1
);

INSERT OR IGNORE INTO announcements VALUES
    (1, 1, 'System Maintenance Window — March 15',       'All systems will undergo scheduled maintenance on March 15, 2024 from 2:00 AM to 6:00 AM EST. Please save your work beforehand. VPN access will be intermittent during this window.', '2024-03-10', 1),
    (2, 2, 'Q4 All-Hands Meeting Scheduled',             'The Q4 all-hands meeting is scheduled for December 20, 2024 at 3:00 PM EST. All departments are expected to attend. Agenda includes annual review and 2025 planning.', '2024-12-01', 1),
    (3, 1, 'New Password Policy Effective Immediately',   'As of today, all passwords must be at least 16 characters and include uppercase, lowercase, numbers, and special characters. Password rotation is now every 90 days. Contact IT for assistance.', '2024-09-15', 0),
    (4, 2, 'Welcome New Engineering Hires',               'Please welcome our new team members joining Engineering this month: Sarah K. (Backend), James L. (Frontend), and Priya M. (DevOps). They will be going through onboarding this week.', '2024-10-01', 0),
    (5, 1, 'Office WiFi Network Change',                  'The corporate WiFi SSID is changing from "CorpNet" to "CorpSuite-Secure" starting Monday. Please reconnect using your existing credentials. Guest network remains unchanged.', '2024-11-05', 0);

INSERT OR IGNORE INTO shared_files VALUES
    (1, 1, 'employee_handbook_2024.pdf',    'Company employee handbook — policies, benefits, and code of conduct.', 'everyone',    '2024-01-15'),
    (2, 2, 'engineering_onboarding.pdf',    'Onboarding guide for new engineering team members.',                  'engineering', '2024-03-20'),
    (3, 1, 'brand_guidelines_v2.pdf',       'Official brand guidelines including logos, colors, and typography.',  'everyone',    '2024-05-10'),
    (4, 2, 'sprint_planning_template.xlsx', 'Template for bi-weekly sprint planning sessions.',                    'engineering', '2024-06-01'),
    (5, 4, 'sales_deck_2024.pptx',          'Customer-facing sales presentation deck for 2024.',                   'sales',       '2024-07-15'),
    (6, 1, 'holiday_calendar_2024.pdf',     'Company holiday schedule and PTO policy for 2024.',                   'everyone',    '2024-01-02'),
    (7, 2, 'code_style_guide.md',           'Coding standards and style guide for all repositories.',              'engineering', '2024-04-12');

INSERT OR IGNORE INTO catalog VALUES
    (1, 'Laptop Pro X1',        '14" business laptop, Intel i7, 32GB RAM, 1TB SSD',              1299.99, 'Computers',     1),
    (2, 'Monitor 4K UHD 27"',   '27 inch 4K IPS display, USB-C hub, adjustable stand',            599.99, 'Monitors',      1),
    (3, 'Mechanical Keyboard',  'Cherry MX Brown switches, wireless, backlit',                     149.99, 'Peripherals',   1),
    (4, 'USB-C Hub 8-in-1',     'HDMI, 3x USB-A, SD card, ethernet, PD charging',                  49.99, 'Accessories',   1),
    (5, 'Standing Desk',        'Electric height-adjustable desk, 60x30 inch, memory presets',     799.99, 'Furniture',     1),
    (6, 'Ergonomic Chair',      'Mesh back, lumbar support, adjustable arms and headrest',          549.99, 'Furniture',     1),
    (7, 'Webcam HD Pro',        '1080p webcam with noise-canceling microphone, auto-focus',          89.99, 'Peripherals',   1),
    (8, 'Noise-Canceling Headset', 'Wireless ANC headset, 30hr battery, Teams/Zoom certified',     279.99, 'Audio',         0),
    (9, 'Server Rack Unit 42U', '42U rack, cable management, cooling fans, locking doors',        8999.99, 'Infrastructure', 1),
    (10, 'Portable SSD 2TB',    'USB-C external SSD, 2TB, hardware encrypted, shock resistant',    179.99, 'Storage',       1);

INSERT OR IGNORE INTO activity_log VALUES
    (1,  3, 'login',           'session',           '2024-12-01 09:15:22'),
    (2,  3, 'view',            'document/3',        '2024-12-01 09:20:11'),
    (3,  3, 'download',        'shared_file/1',     '2024-12-01 09:25:45'),
    (4,  3, 'view',            'order/1',           '2024-12-01 10:02:33'),
    (5,  3, 'view',            'order/2',           '2024-12-01 10:03:01'),
    (6,  4, 'login',           'session',           '2024-12-01 08:45:10'),
    (7,  4, 'view',            'catalog',           '2024-12-01 08:50:22'),
    (8,  4, 'view',            'order/3',           '2024-12-01 09:10:55'),
    (9,  4, 'submit',          'ticket/2',          '2024-12-01 09:30:40'),
    (10, 1, 'login',           'session',           '2024-12-01 07:00:05'),
    (11, 1, 'modify',          'settings/jwt_secret','2024-12-01 07:15:33'),
    (12, 1, 'delete',          'user/6',            '2024-12-01 07:20:10'),
    (13, 2, 'login',           'session',           '2024-12-01 08:30:00'),
    (14, 2, 'view',            'report/1',          '2024-12-01 08:35:12'),
    (15, 2, 'view',            'report/3',          '2024-12-01 08:40:44'),
    (16, 5, 'login',           'session',           '2024-12-01 11:00:00'),
    (17, 5, 'view',            'announcement/1',    '2024-12-01 11:05:20'),
    (18, 3, 'logout',          'session',           '2024-12-01 17:30:00'),
    (19, 4, 'logout',          'session',           '2024-12-01 17:45:00'),
    (20, 3, 'login',           'session',           '2024-12-02 09:00:15');

INSERT OR IGNORE INTO tickets VALUES
    (1, 3, 'VPN connection dropping intermittently',       'My VPN connection drops every 30 minutes. Using FortiClient on macOS 14.1. Have tried reinstalling.',                           'open',     'medium', 1),
    (2, 4, 'Need access to Salesforce sandbox',            'Requesting access to the Salesforce QA sandbox for testing the new lead scoring integration.',                                  'open',     'low',    1),
    (3, 3, 'Build pipeline failing on staging',            'The CI/CD pipeline for the auth-service repo fails during the Docker build step. Error: layer not found. Started after merge #247.', 'in_progress', 'high', 1),
    (4, 1, 'Rotate production database credentials',       'Scheduled credential rotation for the production PostgreSQL cluster. Coordinate with DevOps for zero-downtime rollover.',       'open',     'critical', 0),
    (5, 2, 'Upgrade Kubernetes cluster to 1.29',           'Plan and execute K8s cluster upgrade from 1.27 to 1.29. Need to verify all helm charts are compatible first.',                  'open',     'medium', 0),
    (6, 4, 'Printer on 3rd floor not working',             'The HP LaserJet on the 3rd floor sales area shows "offline" status. Have tried power cycling. Ticket for facilities/IT.',       'resolved', 'low',    1),
    (7, 3, 'Request for additional monitor',               'Requesting a second 4K monitor for dual-screen setup. Manager approved. Please order from catalog item #2.',                    'resolved', 'low',    1);
"""


def init_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.executescript(DB_SEED_SQL)
    conn.close()


def create_app(db_path):
    template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
    app = Flask(__name__, template_folder=template_dir)
    app.config["DB_PATH"] = db_path
    app.secret_key = "corpsuite-session-key-2024"

    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DB_PATH"])
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_db(e=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def get_current_user():
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
        elif "token" in session:
            token = session["token"]
        else:
            return None
        db = get_db()
        row = db.execute(
            "SELECT u.id, u.username, u.role, u.department "
            "FROM users u JOIN tokens t ON u.id = t.user_id "
            "WHERE t.token = ?",
            (token,),
        ).fetchone()
        return dict(row) if row else None

    def require_auth():
        user = get_current_user()
        if not user:
            return None, (jsonify({"error": "Authentication required"}), 401)
        return user, None

    def require_web_auth():
        user = get_current_user()
        if not user:
            return None, redirect(url_for("login_page"))
        return user, None

    # ── Web Routes ──

    @app.route("/")
    def index():
        return redirect(url_for("login_page"))

    @app.route("/login", methods=["GET", "POST"])
    def login_page():
        if request.method == "GET":
            if "token" in session:
                return redirect(url_for("dashboard"))
            return render_template("login.html", error=None)

        token = request.form.get("token", "").strip()
        if not token:
            return render_template("login.html", error="Access token is required.")

        db = get_db()
        row = db.execute(
            "SELECT u.id, u.username, u.role, u.department "
            "FROM users u JOIN tokens t ON u.id = t.user_id "
            "WHERE t.token = ?",
            (token,),
        ).fetchone()
        if not row:
            return render_template("login.html", error="Invalid token. Please try again.")

        session["token"] = token
        session["user_id"] = row["id"]
        flash("Welcome back, {}!".format(row["username"]), "success")
        return redirect(url_for("dashboard"))

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login_page"))

    @app.route("/dashboard")
    def dashboard():
        user, redir = require_web_auth()
        if redir:
            return redir

        db = get_db()
        orders = [dict(r) for r in db.execute(
            "SELECT id, product, amount, status FROM orders WHERE user_id = ?",
            (user["id"],),
        ).fetchall()]
        documents = [dict(r) for r in db.execute(
            "SELECT id, title, classification FROM documents WHERE user_id = ?",
            (user["id"],),
        ).fetchall()]
        reports = [dict(r) for r in db.execute(
            "SELECT id, title, visibility FROM reports"
        ).fetchall()]
        users = [dict(r) for r in db.execute(
            "SELECT id, username, role, department FROM users"
        ).fetchall()]

        return render_template("dashboard.html",
            current_user=user, active_page="dashboard",
            orders=orders, documents=documents, reports=reports, users=users)

    @app.route("/users")
    def users_page():
        user, redir = require_web_auth()
        if redir:
            return redir

        db = get_db()
        users = [dict(r) for r in db.execute(
            "SELECT id, username, role, department FROM users"
        ).fetchall()]

        return render_template("users.html",
            current_user=user, active_page="users", users=users)

    @app.route("/users/<int:user_id>")
    def user_detail_page(user_id):
        user, redir = require_web_auth()
        if redir:
            return redir

        db = get_db()
        if user["role"] == "admin" or user["id"] == user_id:
            row = db.execute(
                "SELECT id, username, role, email, phone, department FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        else:
            row = db.execute(
                "SELECT id, username, role, department FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()

        if not row:
            flash("User not found.", "danger")
            return redirect(url_for("users_page"))

        return render_template("user_detail.html",
            current_user=user, active_page="users", profile=dict(row))

    @app.route("/orders")
    def orders_page():
        user, redir = require_web_auth()
        if redir:
            return redir

        db = get_db()
        orders = [dict(r) for r in db.execute(
            "SELECT id, product, amount, status FROM orders WHERE user_id = ?",
            (user["id"],),
        ).fetchall()]

        return render_template("orders.html",
            current_user=user, active_page="orders", orders=orders)

    @app.route("/orders/<int:order_id>")
    def order_detail_page(order_id):
        user, redir = require_web_auth()
        if redir:
            return redir

        db = get_db()
        row = db.execute(
            "SELECT id, user_id, product, amount, status, shipping_address FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()

        if not row:
            flash("Order not found.", "danger")
            return redirect(url_for("orders_page"))

        return render_template("order_detail.html",
            current_user=user, active_page="orders", order=dict(row))

    @app.route("/documents")
    def documents_page():
        user, redir = require_web_auth()
        if redir:
            return redir

        db = get_db()
        rows = [dict(r) for r in db.execute(
            "SELECT id, title, classification FROM documents WHERE user_id = ?",
            (user["id"],),
        ).fetchall()]

        return render_template("documents.html",
            current_user=user, active_page="documents", documents=rows)

    @app.route("/documents/<int:doc_id>")
    def document_detail_page(doc_id):
        user, redir = require_web_auth()
        if redir:
            return redir

        db = get_db()
        row = db.execute(
            "SELECT id, user_id, title, content, classification FROM documents WHERE id = ? AND user_id = ?",
            (doc_id, user["id"]),
        ).fetchone()

        if not row:
            flash("Document not found.", "danger")
            return redirect(url_for("documents_page"))

        return render_template("document_detail.html",
            current_user=user, active_page="documents", document=dict(row))

    @app.route("/reports")
    def reports_page():
        user, redir = require_web_auth()
        if redir:
            return redir

        db = get_db()
        rows = [dict(r) for r in db.execute(
            "SELECT id, title, visibility FROM reports"
        ).fetchall()]

        return render_template("reports.html",
            current_user=user, active_page="reports", reports=rows)

    @app.route("/reports/<int:report_id>")
    def report_detail_page(report_id):
        user, redir = require_web_auth()
        if redir:
            return redir

        db = get_db()
        row = db.execute(
            "SELECT id, created_by, title, content, visibility FROM reports WHERE id = ?",
            (report_id,),
        ).fetchone()

        if not row:
            flash("Report not found.", "danger")
            return redirect(url_for("reports_page"))

        return render_template("report_detail.html",
            current_user=user, active_page="reports", report=dict(row))

    @app.route("/admin")
    def admin_page():
        user, redir = require_web_auth()
        if redir:
            return redir

        db = get_db()
        config = {}
        admin_users = []

        config_rows = db.execute("SELECT key, value FROM settings").fetchall()
        config = {r["key"]: r["value"] for r in config_rows}

        if user["role"] == "admin":
            admin_users = [dict(r) for r in db.execute(
                "SELECT id, username, role, email, phone, department FROM users"
            ).fetchall()]

        return render_template("admin.html",
            current_user=user, active_page="admin",
            config=config, admin_users=admin_users)

    @app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
    def admin_delete_user(user_id):
        user, redir = require_web_auth()
        if redir:
            return redir

        if user["role"] != "admin":
            flash("Admin access required.", "danger")
            return redirect(url_for("admin_page"))

        db = get_db()
        db.execute("DELETE FROM users WHERE id = ? AND id != ?", (user_id, user["id"]))
        db.commit()
        flash("User deleted successfully.", "success")
        return redirect(url_for("admin_page"))

    @app.route("/announcements")
    def announcements_page():
        user, redir = require_web_auth()
        if redir:
            return redir

        db = get_db()
        rows = [dict(r) for r in db.execute(
            "SELECT a.id, a.title, a.content, a.published_at, a.pinned, u.username as author "
            "FROM announcements a JOIN users u ON a.author_id = u.id "
            "ORDER BY a.pinned DESC, a.published_at DESC"
        ).fetchall()]

        return render_template("announcements.html",
            current_user=user, active_page="announcements", announcements=rows)

    @app.route("/announcements/<int:ann_id>")
    def announcement_detail_page(ann_id):
        user, redir = require_web_auth()
        if redir:
            return redir

        db = get_db()
        row = db.execute(
            "SELECT a.id, a.title, a.content, a.published_at, a.pinned, a.author_id, u.username as author "
            "FROM announcements a JOIN users u ON a.author_id = u.id WHERE a.id = ?",
            (ann_id,),
        ).fetchone()

        if not row:
            flash("Announcement not found.", "danger")
            return redirect(url_for("announcements_page"))

        return render_template("announcement_detail.html",
            current_user=user, active_page="announcements", announcement=dict(row))

    @app.route("/shared")
    def shared_files_page():
        user, redir = require_web_auth()
        if redir:
            return redir

        db = get_db()
        dept = user["department"].lower()
        rows = [dict(r) for r in db.execute(
            "SELECT sf.id, sf.filename, sf.description, sf.shared_with, sf.uploaded_at, u.username as uploader "
            "FROM shared_files sf JOIN users u ON sf.uploaded_by = u.id "
            "WHERE sf.shared_with = 'everyone' OR sf.shared_with = ? "
            "ORDER BY sf.uploaded_at DESC",
            (dept,),
        ).fetchall()]

        return render_template("shared_files.html",
            current_user=user, active_page="shared", files=rows)

    @app.route("/shared/<int:file_id>")
    def shared_file_detail_page(file_id):
        user, redir = require_web_auth()
        if redir:
            return redir

        db = get_db()
        dept = user["department"].lower()
        row = db.execute(
            "SELECT sf.id, sf.filename, sf.description, sf.shared_with, sf.uploaded_at, sf.uploaded_by, u.username as uploader "
            "FROM shared_files sf JOIN users u ON sf.uploaded_by = u.id "
            "WHERE sf.id = ? AND (sf.shared_with = 'everyone' OR sf.shared_with = ?)",
            (file_id, dept),
        ).fetchone()

        if not row:
            flash("File not found or access denied.", "danger")
            return redirect(url_for("shared_files_page"))

        return render_template("shared_file_detail.html",
            current_user=user, active_page="shared", file=dict(row))

    @app.route("/catalog")
    def catalog_page():
        user, redir = require_web_auth()
        if redir:
            return redir

        db = get_db()
        rows = [dict(r) for r in db.execute(
            "SELECT id, name, description, price, category, in_stock FROM catalog ORDER BY category, name"
        ).fetchall()]

        categories = sorted(set(r["category"] for r in rows))

        return render_template("catalog.html",
            current_user=user, active_page="catalog", items=rows, categories=categories)

    @app.route("/catalog/<int:item_id>")
    def catalog_detail_page(item_id):
        user, redir = require_web_auth()
        if redir:
            return redir

        db = get_db()
        row = db.execute(
            "SELECT id, name, description, price, category, in_stock FROM catalog WHERE id = ?",
            (item_id,),
        ).fetchone()

        if not row:
            flash("Catalog item not found.", "danger")
            return redirect(url_for("catalog_page"))

        return render_template("catalog_detail.html",
            current_user=user, active_page="catalog", item=dict(row))

    @app.route("/activity")
    def activity_page():
        user, redir = require_web_auth()
        if redir:
            return redir

        db = get_db()
        rows = [dict(r) for r in db.execute(
            "SELECT id, action, target, timestamp FROM activity_log "
            "WHERE user_id = ? ORDER BY timestamp DESC",
            (user["id"],),
        ).fetchall()]

        return render_template("activity.html",
            current_user=user, active_page="activity", logs=rows)

    @app.route("/tickets")
    def tickets_page():
        user, redir = require_web_auth()
        if redir:
            return redir

        db = get_db()
        public_tickets = [dict(r) for r in db.execute(
            "SELECT t.id, t.subject, t.status, t.priority, t.is_public, u.username as creator "
            "FROM tickets t JOIN users u ON t.created_by = u.id "
            "WHERE t.is_public = 1 "
            "ORDER BY t.id DESC"
        ).fetchall()]
        my_private = [dict(r) for r in db.execute(
            "SELECT t.id, t.subject, t.status, t.priority, t.is_public, u.username as creator "
            "FROM tickets t JOIN users u ON t.created_by = u.id "
            "WHERE t.is_public = 0 AND t.created_by = ? "
            "ORDER BY t.id DESC",
            (user["id"],),
        ).fetchall()]

        return render_template("tickets.html",
            current_user=user, active_page="tickets",
            public_tickets=public_tickets, my_private=my_private)

    @app.route("/tickets/<int:ticket_id>")
    def ticket_detail_page(ticket_id):
        user, redir = require_web_auth()
        if redir:
            return redir

        db = get_db()
        row = db.execute(
            "SELECT t.id, t.subject, t.description, t.status, t.priority, t.is_public, t.created_by, u.username as creator "
            "FROM tickets t JOIN users u ON t.created_by = u.id WHERE t.id = ?",
            (ticket_id,),
        ).fetchone()

        if not row:
            flash("Ticket not found.", "danger")
            return redirect(url_for("tickets_page"))

        ticket = dict(row)
        if not ticket["is_public"] and ticket["created_by"] != user["id"]:
            flash("Access denied. This is a private ticket.", "danger")
            return redirect(url_for("tickets_page"))

        return render_template("ticket_detail.html",
            current_user=user, active_page="tickets", ticket=ticket)

    @app.route("/teams")
    def teams_page():
        user, redir = require_web_auth()
        if redir:
            return redir

        db = get_db()
        rows = db.execute("SELECT DISTINCT department FROM users ORDER BY department").fetchall()
        departments = [r["department"] for r in rows]

        return render_template("teams.html",
            current_user=user, active_page="teams", departments=departments)

    @app.route("/teams/<department>")
    def team_detail_page(department):
        user, redir = require_web_auth()
        if redir:
            return redir

        db = get_db()
        members = [dict(r) for r in db.execute(
            "SELECT id, username, role FROM users WHERE department = ?",
            (department,),
        ).fetchall()]

        if not members:
            flash("Department not found.", "danger")
            return redirect(url_for("teams_page"))

        return render_template("team_detail.html",
            current_user=user, active_page="teams",
            department=department, members=members)

    # ── API Routes ──

    @app.route("/api/health")
    def health():
        return jsonify({"status": "ok"})

    @app.route("/api/users")
    def list_users():
        user, err = require_auth()
        if err:
            return err
        db = get_db()
        rows = db.execute("SELECT id, username, role, department FROM users").fetchall()
        return jsonify([dict(r) for r in rows])

    @app.route("/api/users/<int:user_id>")
    def get_user(user_id):
        user, err = require_auth()
        if err:
            return err
        db = get_db()
        if user["role"] == "admin" or user["id"] == user_id:
            row = db.execute(
                "SELECT id, username, role, email, phone, department FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        else:
            row = db.execute(
                "SELECT id, username, role, department FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if not row:
            return jsonify({"error": "User not found"}), 404
        return jsonify(dict(row))

    @app.route("/api/orders")
    def list_orders():
        user, err = require_auth()
        if err:
            return err
        db = get_db()
        rows = db.execute(
            "SELECT id, product, amount, status FROM orders WHERE user_id = ?",
            (user["id"],),
        ).fetchall()
        return jsonify([dict(r) for r in rows])

    @app.route("/api/orders/<int:order_id>")
    def get_order(order_id):
        user, err = require_auth()
        if err:
            return err
        db = get_db()
        row = db.execute(
            "SELECT id, user_id, product, amount, status, shipping_address FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if not row:
            return jsonify({"error": "Order not found"}), 404
        return jsonify(dict(row))

    @app.route("/api/documents")
    def list_documents():
        user, err = require_auth()
        if err:
            return err
        db = get_db()
        rows = db.execute(
            "SELECT id, title, classification FROM documents WHERE user_id = ?",
            (user["id"],),
        ).fetchall()
        return jsonify([dict(r) for r in rows])

    @app.route("/api/documents/<int:doc_id>")
    def get_document(doc_id):
        user, err = require_auth()
        if err:
            return err
        db = get_db()
        row = db.execute(
            "SELECT id, user_id, title, content, classification FROM documents WHERE id = ? AND user_id = ?",
            (doc_id, user["id"]),
        ).fetchone()
        if not row:
            return jsonify({"error": "Document not found"}), 404
        return jsonify(dict(row))

    @app.route("/api/reports")
    def list_reports():
        user, err = require_auth()
        if err:
            return err
        db = get_db()
        rows = db.execute("SELECT id, title, visibility FROM reports").fetchall()
        return jsonify([dict(r) for r in rows])

    @app.route("/api/reports/<int:report_id>")
    def get_report(report_id):
        user, err = require_auth()
        if err:
            return err
        db = get_db()
        row = db.execute(
            "SELECT id, created_by, title, content, visibility FROM reports WHERE id = ?",
            (report_id,),
        ).fetchone()
        if not row:
            return jsonify({"error": "Report not found"}), 404
        return jsonify(dict(row))

    @app.route("/api/admin/config")
    def admin_config():
        user, err = require_auth()
        if err:
            return err
        db = get_db()
        rows = db.execute("SELECT key, value FROM settings").fetchall()
        return jsonify({r["key"]: r["value"] for r in rows})

    @app.route("/api/admin/users")
    def admin_users():
        user, err = require_auth()
        if err:
            return err
        if user["role"] != "admin":
            return jsonify({"error": "Admin access required"}), 403
        db = get_db()
        rows = db.execute(
            "SELECT id, username, role, email, phone, department FROM users"
        ).fetchall()
        return jsonify([dict(r) for r in rows])

    @app.route("/api/admin/users/<int:user_id>", methods=["DELETE"])
    def delete_user(user_id):
        user, err = require_auth()
        if err:
            return err
        if user["role"] != "admin":
            return jsonify({"error": "Admin access required"}), 403
        db = get_db()
        db.execute("DELETE FROM users WHERE id = ? AND id != ?", (user_id, user["id"]))
        db.commit()
        return jsonify({"status": "deleted"})

    # ── False-Positive API Routes ──
    # These endpoints are intentionally accessible and not vulnerabilities.

    @app.route("/api/announcements")
    def list_announcements():
        user, err = require_auth()
        if err:
            return err
        db = get_db()
        rows = db.execute(
            "SELECT a.id, a.title, a.content, a.published_at, a.pinned, a.author_id, u.username as author "
            "FROM announcements a JOIN users u ON a.author_id = u.id "
            "ORDER BY a.pinned DESC, a.published_at DESC"
        ).fetchall()
        return jsonify([dict(r) for r in rows])

    @app.route("/api/announcements/<int:ann_id>")
    def get_announcement(ann_id):
        user, err = require_auth()
        if err:
            return err
        db = get_db()
        row = db.execute(
            "SELECT a.id, a.title, a.content, a.published_at, a.pinned, a.author_id, u.username as author "
            "FROM announcements a JOIN users u ON a.author_id = u.id WHERE a.id = ?",
            (ann_id,),
        ).fetchone()
        if not row:
            return jsonify({"error": "Announcement not found"}), 404
        return jsonify(dict(row))

    @app.route("/api/shared-files")
    def list_shared_files():
        user, err = require_auth()
        if err:
            return err
        db = get_db()
        dept = user["department"].lower()
        rows = db.execute(
            "SELECT sf.id, sf.filename, sf.description, sf.shared_with, sf.uploaded_at, sf.uploaded_by, u.username as uploader "
            "FROM shared_files sf JOIN users u ON sf.uploaded_by = u.id "
            "WHERE sf.shared_with = 'everyone' OR sf.shared_with = ? "
            "ORDER BY sf.uploaded_at DESC",
            (dept,),
        ).fetchall()
        return jsonify([dict(r) for r in rows])

    @app.route("/api/shared-files/<int:file_id>")
    def get_shared_file(file_id):
        user, err = require_auth()
        if err:
            return err
        db = get_db()
        dept = user["department"].lower()
        row = db.execute(
            "SELECT sf.id, sf.filename, sf.description, sf.shared_with, sf.uploaded_at, sf.uploaded_by, u.username as uploader "
            "FROM shared_files sf JOIN users u ON sf.uploaded_by = u.id "
            "WHERE sf.id = ? AND (sf.shared_with = 'everyone' OR sf.shared_with = ?)",
            (file_id, dept),
        ).fetchone()
        if not row:
            return jsonify({"error": "File not found or access denied"}), 404
        return jsonify(dict(row))

    @app.route("/api/catalog")
    def list_catalog():
        user, err = require_auth()
        if err:
            return err
        db = get_db()
        rows = db.execute(
            "SELECT id, name, description, price, category, in_stock FROM catalog ORDER BY category, name"
        ).fetchall()
        return jsonify([dict(r) for r in rows])

    @app.route("/api/catalog/<int:item_id>")
    def get_catalog_item(item_id):
        user, err = require_auth()
        if err:
            return err
        db = get_db()
        row = db.execute(
            "SELECT id, name, description, price, category, in_stock FROM catalog WHERE id = ?",
            (item_id,),
        ).fetchone()
        if not row:
            return jsonify({"error": "Item not found"}), 404
        return jsonify(dict(row))

    @app.route("/api/activity")
    def list_activity():
        user, err = require_auth()
        if err:
            return err
        db = get_db()
        rows = db.execute(
            "SELECT id, action, target, timestamp FROM activity_log "
            "WHERE user_id = ? ORDER BY timestamp DESC",
            (user["id"],),
        ).fetchall()
        return jsonify([dict(r) for r in rows])

    @app.route("/api/tickets")
    def list_tickets():
        user, err = require_auth()
        if err:
            return err
        db = get_db()
        rows = db.execute(
            "SELECT t.id, t.subject, t.status, t.priority, t.is_public, t.created_by, u.username as creator "
            "FROM tickets t JOIN users u ON t.created_by = u.id "
            "WHERE t.is_public = 1 OR t.created_by = ? "
            "ORDER BY t.id DESC",
            (user["id"],),
        ).fetchall()
        return jsonify([dict(r) for r in rows])

    @app.route("/api/tickets/<int:ticket_id>")
    def get_ticket(ticket_id):
        user, err = require_auth()
        if err:
            return err
        db = get_db()
        row = db.execute(
            "SELECT t.id, t.subject, t.description, t.status, t.priority, t.is_public, t.created_by, u.username as creator "
            "FROM tickets t JOIN users u ON t.created_by = u.id WHERE t.id = ?",
            (ticket_id,),
        ).fetchone()
        if not row:
            return jsonify({"error": "Ticket not found"}), 404
        ticket = dict(row)
        if not ticket["is_public"] and ticket["created_by"] != user["id"]:
            return jsonify({"error": "Access denied"}), 403
        return jsonify(ticket)

    @app.route("/api/teams")
    def list_teams():
        user, err = require_auth()
        if err:
            return err
        db = get_db()
        rows = db.execute("SELECT DISTINCT department FROM users ORDER BY department").fetchall()
        return jsonify([{"department": r["department"]} for r in rows])

    @app.route("/api/teams/<department>")
    def get_team(department):
        user, err = require_auth()
        if err:
            return err
        db = get_db()
        rows = db.execute(
            "SELECT id, username, role FROM users WHERE department = ?",
            (department,),
        ).fetchall()
        if not rows:
            return jsonify({"error": "Department not found"}), 404
        return jsonify({"department": department, "members": [dict(r) for r in rows]})

    return app

if __name__ == "__main__":
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.db")
    if not os.path.exists(DB_PATH):
        init_db(DB_PATH)
    app = create_app(DB_PATH)
    app.run(host="0.0.0.0", port="5000")