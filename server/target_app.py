import sqlite3
from flask import Flask, g, jsonify, request


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
"""


def init_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.executescript(DB_SEED_SQL)
    conn.close()


def create_app(db_path):
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path

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
        if not auth.startswith("Bearer "):
            return None
        token = auth[7:]
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

    return app
