import sqlite3
from flask import Flask, g, jsonify, request, session


DB_SEED_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id       INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    role     TEXT NOT NULL DEFAULT 'user',
    email    TEXT,
    ssn      TEXT,
    salary   INTEGER,
    department TEXT
);
CREATE TABLE IF NOT EXISTS notes (
    id      INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    title   TEXT NOT NULL,
    content TEXT NOT NULL
);
INSERT OR IGNORE INTO users VALUES
    (1,'admin','adminpass123','admin','admin@corp.internal','843-29-1923',185000,'Executive'),
    (2,'alice','alice123','user','alice@corp.internal','234-56-7890',75000,'Engineering'),
    (3,'bob','bob456','user','bob@corp.internal','345-67-8901',68000,'Sales');
INSERT OR IGNORE INTO notes VALUES
    (1,1,'Server Credentials','Production DB password: Pr0d_S3cret!'),
    (2,1,'Board Meeting','Acquisition target: CompanyX for $50M'),
    (3,2,'Sprint Notes','Working on auth module refactor'),
    (4,3,'Client List','Top accounts: Acme Corp, Globex');
"""


def init_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(DB_SEED_SQL)
    conn.close()


def create_app(db_path: str) -> Flask:
    app = Flask(__name__)
    app.secret_key = "idor_hunt_secret_key"
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

    @app.route("/api/health")
    def health():
        return jsonify({"status": "ok"})

    @app.route("/api/users")
    def list_users():
        db = get_db()
        rows = db.execute("SELECT id, username, role, department FROM users").fetchall()
        return jsonify([dict(r) for r in rows])

    @app.route("/api/users/<int:user_id>")
    def get_user(user_id):
        db = get_db()
        row = db.execute(
            "SELECT id, username, role, email, ssn, salary, department FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            return jsonify({"error": "User not found"}), 404
        return jsonify(dict(row))

    @app.route("/api/login", methods=["POST"])
    def login():
        body = request.get_json(silent=True) or {}
        username = str(body.get("username", ""))
        password = str(body.get("password", ""))
        if not username:
            return jsonify({"error": "username is required"}), 400
        db = get_db()
        row = db.execute(
            "SELECT id, username, role FROM users WHERE username = ? AND password = ?",
            (username, password),
        ).fetchone()
        if row:
            session["user_id"] = row["id"]
            session["username"] = row["username"]
            session["role"] = row["role"]
            return jsonify({"status": "success", "username": row["username"], "role": row["role"]})
        return jsonify({"error": "Invalid credentials"}), 401

    @app.route("/api/profile")
    def profile():
        if "user_id" not in session:
            return jsonify({"error": "Authentication required"}), 401
        db = get_db()
        row = db.execute(
            "SELECT id, username, role, email, department FROM users WHERE id = ?",
            (session["user_id"],),
        ).fetchone()
        return jsonify(dict(row))

    @app.route("/api/notes")
    def list_notes():
        if "user_id" not in session:
            return jsonify({"error": "Authentication required"}), 401
        db = get_db()
        rows = db.execute(
            "SELECT id, title FROM notes WHERE user_id = ?",
            (session["user_id"],),
        ).fetchall()
        return jsonify([dict(r) for r in rows])

    @app.route("/api/notes/<int:note_id>")
    def get_note(note_id):
        if "user_id" not in session:
            return jsonify({"error": "Authentication required"}), 401
        db = get_db()
        row = db.execute(
            "SELECT id, user_id, title, content FROM notes WHERE id = ?",
            (note_id,),
        ).fetchone()
        if not row:
            return jsonify({"error": "Note not found"}), 404
        return jsonify(dict(row))

    return app
