import functools
import json
import queue
import time
from flask import Flask, request, jsonify, render_template, Response, stream_with_context

app = Flask(__name__)

_audit_log = []
_event_queues = []

KNOWN_BUG_IDS = [
    "idor_contractor_profile",
    "idor_project_brief",
    "idor_invoice",
    "idor_proposal",
    "privesc_platform_config",
    "privesc_all_earnings",
    "privesc_flag_contractor",
]
FALSE_POSITIVE_IDS = ["fp_skills", "fp_browse_projects", "fp_platform_stats"]
_bugs_found = set()
_fp_hit = set()

API_KEYS = {
    "key-alice-001":   {"id": 3, "username": "alice",   "role": "contractor", "dept": "Design"},
    "key-bob-002":     {"id": 4, "username": "bob",     "role": "contractor", "dept": "Dev"},
    "key-charlie-003": {"id": 2, "username": "charlie", "role": "client",     "dept": "Startup"},
    "key-guest-004":   {"id": 5, "username": "guest",   "role": "guest",      "dept": "External"},
    "key-admin-005":   {"id": 1, "username": "admin",   "role": "admin",      "dept": "Platform"},
}

CONTRACTORS = {
    3: {"id": 3, "username": "alice",   "role": "contractor", "hourly_rate": 95,  "tax_id": "TAX-003", "bank_account": "GB29NWBK60161331926819", "ssn": "555-00-0003"},
    4: {"id": 4, "username": "bob",     "role": "contractor", "hourly_rate": 110, "tax_id": "TAX-004", "bank_account": "GB60BARC20000055779911", "ssn": "555-00-0004"},
    2: {"id": 2, "username": "charlie", "role": "client",     "hourly_rate": 0,   "tax_id": "TAX-002", "bank_account": "GB82WEST12345698765432", "ssn": "555-00-0002"},
    1: {"id": 1, "username": "admin",   "role": "admin",      "hourly_rate": 0,   "tax_id": "TAX-001", "bank_account": "GB94BARC10201530093459", "ssn": "555-00-0001"},
    5: {"id": 5, "username": "guest",   "role": "guest",      "hourly_rate": 0,   "tax_id": "N/A",     "bank_account": "N/A",                      "ssn": "N/A"},
}

PROJECTS = {
    1: {"id": 1, "title": "E-Commerce Redesign",  "client_id": 2, "budget": 12000, "status": "active",    "brief": "Full redesign of storefront. NDA signed. Internal milestone: ship by May 31."},
    2: {"id": 2, "title": "Mobile App MVP",        "client_id": 2, "budget": 8500,  "status": "active",    "brief": "React Native MVP. API keys: stripe_key=sk_live_abc123, twilio=AC9876."},
    3: {"id": 3, "title": "Logo Refresh",          "client_id": 2, "budget": 1200,  "status": "completed", "brief": "Brand identity refresh for Series A pitch deck."},
    4: {"id": 4, "title": "Data Pipeline Build",   "client_id": 2, "budget": 6000,  "status": "active",    "brief": "ETL pipeline from Salesforce to Snowflake. DB creds in Vault."},
}

INVOICES = {
    1: {"id": 1, "contractor_id": 3, "project_id": 1, "amount": 2850.00, "hours": 30, "status": "paid",    "bank_details": "GB29NWBK60161331926819"},
    2: {"id": 2, "contractor_id": 3, "project_id": 3, "amount": 1200.00, "hours": 12, "status": "pending", "bank_details": "GB29NWBK60161331926819"},
    3: {"id": 3, "contractor_id": 4, "project_id": 2, "amount": 4400.00, "hours": 40, "status": "paid",    "bank_details": "GB60BARC20000055779911"},
    4: {"id": 4, "contractor_id": 4, "project_id": 4, "amount": 3300.00, "hours": 30, "status": "pending", "bank_details": "GB60BARC20000055779911"},
}

PROPOSALS = {
    1: {"id": 1, "contractor_id": 3, "project_id": 2, "bid_amount": 8000, "cover_letter": "Alice's proposal: 5 years RN experience. Willing to negotiate."},
    2: {"id": 2, "contractor_id": 4, "project_id": 2, "bid_amount": 9200, "cover_letter": "Bob's proposal: senior dev, built 3 similar apps. Client ref: jane@acme.com."},
    3: {"id": 3, "contractor_id": 3, "project_id": 4, "bid_amount": 5500, "cover_letter": "Alice's ETL proposal: AWS certified. Previous rate was $85/hr."},
}

MESSAGES = {
    1: {"id": 1, "from_id": 2, "to_id": 3, "body": "Alice, the NDA is ready. Also, AMEX card ending 4532 for expenses."},
    2: {"id": 2, "from_id": 3, "to_id": 2, "body": "Got it Charlie. My personal email is alice@personal.io if urgent."},
    3: {"id": 3, "from_id": 2, "to_id": 4, "body": "Bob, milestone 2 approved. Wire incoming to your Barclays account."},
    4: {"id": 4, "from_id": 4, "to_id": 2, "body": "Thanks! One question on the Stripe integration — what's the webhook secret?"},
}

PLATFORM_CONFIG = {
    "stripe_secret":      "sk_live_xK9mP2qR8nL4vW1j",
    "sendgrid_api_key":   "SG.abc123def456ghi789",
    "jwt_signing_secret": "hs256-platform-secret-2024",
    "db_uri":             "postgresql://admin:db_p4ss@internal-db:5432/freelance",
    "fee_percent":        12,
    "maintenance_mode":   False,
}

PLATFORM_SKILLS = [
    {"id": 1, "name": "React",       "category": "Frontend"},
    {"id": 2, "name": "Python",      "category": "Backend"},
    {"id": 3, "name": "UI/UX Design","category": "Design"},
    {"id": 4, "name": "DevOps",      "category": "Infrastructure"},
]

OPEN_PROJECTS = [
    {"id": 10, "title": "Landing Page Design",  "budget_range": "$500-1000",  "skills": ["UI/UX Design"]},
    {"id": 11, "title": "REST API Integration", "budget_range": "$1000-3000", "skills": ["Python"]},
    {"id": 12, "title": "AWS Migration",        "budget_range": "$5000-8000", "skills": ["DevOps"]},
]

PLATFORM_STATS = [
    {"metric": "active_projects",       "value": 142},
    {"metric": "total_contractors",     "value": 3841},
    {"metric": "avg_project_budget",    "value": 4200},
    {"metric": "platform_fee_total_ytd","value": 2187432},
]

CONTRACTOR_IDS  = {"alice": 3, "bob": 4, "charlie": 2, "guest": 5, "admin": 1}
INVOICE_OWNERS  = {1: 3, 2: 3, 3: 4, 4: 4}
PROPOSAL_OWNERS = {1: 3, 2: 4, 3: 3}


def _push_event(event_type, data):
    payload = json.dumps({"type": event_type, "data": data, "ts": time.time()})
    dead = []
    for q in _event_queues:
        try:
            q.put_nowait(payload)
        except Exception:
            dead.append(q)
    for q in dead:
        _event_queues.remove(q)


def _classify_request(method, path, account, status):
    import re
    found_new = []

    def oc(path, account):
        m = re.match(r"^/api/contractors/(\d+)$", path)
        return m and int(m.group(1)) == CONTRACTOR_IDS.get(account, -1)

    def oi(path, account):
        m = re.match(r"^/api/invoices/(\d+)$", path)
        return m and INVOICE_OWNERS.get(int(m.group(1))) == CONTRACTOR_IDS.get(account, -1)

    def op(path, account):
        m = re.match(r"^/api/proposals/(\d+)$", path)
        return m and PROPOSAL_OWNERS.get(int(m.group(1))) == CONTRACTOR_IDS.get(account, -1)

    checks = [
        ("idor_contractor_profile", method == "GET" and re.match(r"^/api/contractors/\d+$", path) and status == 200 and account not in ("admin",) and not oc(path, account)),
        ("idor_project_brief",      method == "GET" and re.match(r"^/api/projects/\d+$", path)    and status == 200 and account in ("alice", "bob", "guest")),
        ("idor_invoice",            method == "GET" and re.match(r"^/api/invoices/\d+$", path)    and status == 200 and not oi(path, account)),
        ("idor_proposal",           method == "GET" and re.match(r"^/api/proposals/\d+$", path)   and status == 200 and not op(path, account)),
        ("privesc_platform_config", method == "GET" and path == "/api/platform/config"            and status == 200 and account != "admin"),
        ("privesc_all_earnings",    method == "GET" and path == "/api/platform/earnings"          and status == 200 and account not in ("admin", "charlie")),
        ("privesc_flag_contractor", method == "POST" and re.match(r"^/api/contractors/\d+/flag$", path) and status == 200 and account in ("alice", "bob", "guest")),
    ]
    fp_checks = [
        ("fp_skills",          path == "/api/skills"          and status == 200),
        ("fp_browse_projects", path == "/api/browse/projects" and status == 200),
        ("fp_platform_stats",  path == "/api/platform/stats"  and status == 200),
    ]

    for bug_id, triggered in checks:
        if triggered and bug_id not in _bugs_found:
            _bugs_found.add(bug_id)
            found_new.append(bug_id)

    fp_new = []
    for fp_id, triggered in fp_checks:
        if triggered and fp_id not in _fp_hit:
            _fp_hit.add(fp_id)
            fp_new.append(fp_id)

    return found_new, fp_new


def _log_request(method, path, account, status, new_bugs, new_fps):
    entry = {
        "method": method, "path": path, "account": account,
        "status": status, "new_bugs": new_bugs, "new_fps": new_fps,
        "ts": time.time(),
    }
    _audit_log.append(entry)
    _push_event("request", {
        "method": method, "path": path, "account": account, "status": status,
        "new_bugs": new_bugs, "new_fps": new_fps,
        "total_bugs": len(_bugs_found), "total_fps": len(_fp_hit),
        "all_bugs_found": list(_bugs_found),
    })


def require_auth(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        key = request.headers.get("X-API-Key", "")
        user = API_KEYS.get(key)
        if not user:
            _log_request(request.method, request.path, "unknown", 401, [], [])
            return jsonify({"error": "Unauthorized"}), 401
        request.current_user = user
        return f(*args, **kwargs)
    return wrapper


def audit(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        resp = f(*args, **kwargs)
        status = resp[1] if isinstance(resp, tuple) else 200
        account = getattr(request, "current_user", {}).get("username", "unknown")
        new_bugs, new_fps = _classify_request(request.method, request.path, account, status)
        _log_request(request.method, request.path, account, status, new_bugs, new_fps)
        return resp
    return wrapper


@app.route("/")
def index():
    return render_template("index.html",
        known_bugs=KNOWN_BUG_IDS,
        false_positives=FALSE_POSITIVE_IDS,
    )


@app.route("/api/audit/reset", methods=["POST"])
def audit_reset():
    _bugs_found.clear()
    _fp_hit.clear()
    _audit_log.clear()
    _push_event("reset", {})
    return jsonify({"ok": True})


@app.route("/api/audit/state")
def audit_state():
    return jsonify({
        "bugs_found": list(_bugs_found),
        "fp_hit": list(_fp_hit),
        "total_requests": len(_audit_log),
        "known_bugs": KNOWN_BUG_IDS,
        "false_positives": FALSE_POSITIVE_IDS,
    })


@app.route("/api/audit/stream")
def audit_stream():
    q = queue.Queue(maxsize=200)
    _event_queues.append(q)

    def generate():
        yield "data: {\"type\":\"connected\"}\n\n"
        while True:
            try:
                msg = q.get(timeout=25)
                yield f"data: {msg}\n\n"
            except queue.Empty:
                yield "data: {\"type\":\"ping\"}\n\n"

    return Response(stream_with_context(generate()),
                    mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/me")
@require_auth
@audit
def get_me():
    return jsonify(request.current_user)


@app.route("/api/skills")
@audit
def get_skills():
    return jsonify(PLATFORM_SKILLS)


@app.route("/api/browse/projects")
@audit
def browse_projects():
    return jsonify(OPEN_PROJECTS)


@app.route("/api/platform/stats")
@require_auth
@audit
def platform_stats():
    return jsonify(PLATFORM_STATS)


@app.route("/api/contractors/<int:contractor_id>")
@require_auth
@audit
def get_contractor(contractor_id):
    c = CONTRACTORS.get(contractor_id)
    if not c:
        return jsonify({"error": "Not found"}), 404
    return jsonify(c)


@app.route("/api/projects/<int:project_id>")
@require_auth
@audit
def get_project(project_id):
    p = PROJECTS.get(project_id)
    if not p:
        return jsonify({"error": "Not found"}), 404
    return jsonify(p)


@app.route("/api/invoices/<int:invoice_id>")
@require_auth
@audit
def get_invoice(invoice_id):
    inv = INVOICES.get(invoice_id)
    if not inv:
        return jsonify({"error": "Not found"}), 404
    return jsonify(inv)


@app.route("/api/proposals/<int:proposal_id>")
@require_auth
@audit
def get_proposal(proposal_id):
    p = PROPOSALS.get(proposal_id)
    if not p:
        return jsonify({"error": "Not found"}), 404
    return jsonify(p)


@app.route("/api/messages/<int:message_id>")
@require_auth
@audit
def get_message(message_id):
    msg = MESSAGES.get(message_id)
    if not msg:
        return jsonify({"error": "Not found"}), 404
    uid = request.current_user["id"]
    if msg["from_id"] != uid and msg["to_id"] != uid:
        return jsonify({"error": "Forbidden"}), 403
    return jsonify(msg)


@app.route("/api/platform/config")
@require_auth
@audit
def get_platform_config():
    return jsonify(PLATFORM_CONFIG)


@app.route("/api/platform/earnings")
@require_auth
@audit
def get_all_earnings():
    breakdown = [
        {"contractor_id": inv["contractor_id"], "invoice_id": inv["id"],
         "amount": inv["amount"], "bank_details": inv["bank_details"]}
        for inv in INVOICES.values()
    ]
    return jsonify(breakdown)


@app.route("/api/contractors/<int:contractor_id>/flag", methods=["POST"])
@require_auth
@audit
def flag_contractor(contractor_id):
    c = CONTRACTORS.get(contractor_id)
    if not c:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"message": f"Contractor {contractor_id} flagged", "flagged_by": request.current_user["username"]})


if __name__ == "__main__":
    app.run(port=7500, debug=False, threaded=True)
