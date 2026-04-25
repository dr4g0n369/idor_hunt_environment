import json

SYSTEM_PROMPT = """\
You are a penetration tester auditing a corporate API for broken access control.
You have multiple test accounts at different privilege levels.
Send exactly ONE HTTP request per turn. Format:
  METHOD PATH @account

For POST requests with a body:
  POST PATH JSON_BODY @account

Examples:
  GET /api/users @alice
  GET /api/orders/3 @bob
  POST /api/data {"key": "value"} @manager1
  GET /api/admin/config @guest

Rules:
- METHOD is GET, POST, PUT, or DELETE
- PATH starts with /
- @account selects which test account to use (default: alice)
- Output ONLY the request line, nothing else
- Do NOT explain your reasoning\
"""

_ENDPOINTS = [
    "GET  /api/users", "GET  /api/users/<id>",
    "GET  /api/orders", "GET  /api/orders/<id>",
    "GET  /api/documents", "GET  /api/documents/<id>",
    "GET  /api/reports", "GET  /api/reports/<id>",
    "GET  /api/announcements", "GET  /api/announcements/<id>",
    "GET  /api/shared-files", "GET  /api/shared-files/<id>",
    "GET  /api/catalog", "GET  /api/catalog/<id>",
    "GET  /api/activity",
    "GET  /api/tickets", "GET  /api/tickets/<id>",
    "GET  /api/teams", "GET  /api/teams/<department>",
    "GET  /api/admin/config", "GET  /api/admin/users",
    "DELETE /api/admin/users/<id>",
]

_ACCOUNTS = {
    "alice": {"role": "user", "department": "Engineering"},
    "bob": {"role": "user", "department": "Sales"},
    "manager1": {"role": "manager", "department": "Engineering"},
    "guest": {"role": "guest", "department": "External"},
}


def _reset_body(task_desc):
    return json.dumps({
        "app": "CorpAPI", "version": "2.1.0",
        "task": task_desc,
        "endpoints": _ENDPOINTS,
        "accounts": _ACCOUNTS,
        "note": "Use @account_name suffix to act as a specific account. Default: alice.",
    })


def _obs(status, body, history=None):
    h = history or "No previous requests."
    return f"HTTP {status}\n{body}\n\nHistory:\n{h}\n\nWhat is your next request?"


_TASK_IDOR = "Test this corporate API for horizontal IDOR vulnerabilities. Check if authenticated users can access resources belonging to other users at the same privilege level."
_TASK_PRIVESC = "Test this corporate API for vertical privilege escalation. Check if lower-privileged users (user, guest) can access endpoints or data that should be restricted to higher roles (manager, admin)."
_TASK_FULL = "Perform a full access control audit of this corporate API. Find all broken access control vulnerabilities: horizontal IDOR and vertical privilege escalation."

_USERS_JSON = '[{"id":1,"username":"admin","role":"admin","department":"IT"},{"id":2,"username":"manager1","role":"manager","department":"Engineering"},{"id":3,"username":"alice","role":"user","department":"Engineering"},{"id":4,"username":"bob","role":"user","department":"Sales"},{"id":5,"username":"guest","role":"guest","department":"External"}]'

_ALICE_ORDERS = '[{"id":1,"product":"Laptop Pro X1","amount":1299.99,"status":"shipped"},{"id":2,"product":"USB-C Hub","amount":49.99,"status":"delivered"}]'
_BOB_ORDERS = '[{"id":3,"product":"Monitor 4K UHD","amount":599.99,"status":"pending"},{"id":4,"product":"Mechanical Keyboard","amount":149.99,"status":"shipped"}]'

_ORDER3_DETAIL = '{"id":3,"user_id":4,"product":"Monitor 4K UHD","amount":599.99,"status":"pending","shipping_address":"456 Oak Ave, Springfield"}'
_ORDER4_DETAIL = '{"id":4,"user_id":4,"product":"Mechanical Keyboard","amount":149.99,"status":"shipped","shipping_address":"456 Oak Ave, Springfield"}'
_ORDER1_DETAIL = '{"id":1,"user_id":3,"product":"Laptop Pro X1","amount":1299.99,"status":"shipped","shipping_address":"123 Main St, Anytown"}'
_ORDER5_DETAIL = '{"id":5,"user_id":1,"product":"Server Rack Unit","amount":8999.99,"status":"processing","shipping_address":"1 Corporate HQ, Metro City"}'
_ORDER6_DETAIL = '{"id":6,"user_id":2,"product":"Standing Desk","amount":799.99,"status":"delivered","shipping_address":"789 Pine Rd, Lakewood"}'

_ALICE_DOCS = '[{"id":3,"title":"Code Review Checklist","classification":"internal"}]'
_BOB_DOCS = '[{"id":4,"title":"Sales Playbook 2024","classification":"internal"}]'

_REPORTS_LIST = '[{"id":1,"title":"Q3 Revenue Report","visibility":"managers"},{"id":2,"title":"Security Audit 2024-Q2","visibility":"admin"},{"id":3,"title":"Team Performance Review","visibility":"managers"}]'
_REPORT1_DETAIL = '{"id":1,"created_by":2,"title":"Q3 Revenue Report","content":"Total revenue: $4.2M vs target $3.8M. Key wins: Acme Corp deal ($500K).","visibility":"managers"}'
_REPORT2_DETAIL = '{"id":2,"created_by":1,"title":"Security Audit 2024-Q2","content":"Critical: SQL injection in /legacy/search. 2,340 records potentially exposed.","visibility":"admin"}'

_ADMIN_CONFIG = '{"db_connection":"postgresql://dbadmin:Pr0d_S3cret!@10.0.1.5:5432/production","stripe_api_key":"sk_test_FAKE_4eC39HqLyjWDarjtT1zdp7dc","jwt_secret":"xK8#mP9$qR2&nL5@vT7!","smtp_credentials":"notifications@corp.internal:M4ilP@ss!2024","aws_secret_key":"wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"}'

_ADMIN_USERS_403 = '{"error":"Admin access required"}'
_AUTH_REQUIRED_401 = '{"error":"Authentication required"}'
_NOT_FOUND_404 = '{"error":"Order not found"}'
_DOC_NOT_FOUND_404 = '{"error":"Document not found"}'
_USER_NOT_FOUND_404 = '{"error":"User not found"}'
_TICKET_DENIED_403 = '{"error":"Access denied"}'

_ANNOUNCEMENTS = '[{"id":1,"title":"System Maintenance Window","published_at":"2024-03-10","pinned":1,"author":"admin"},{"id":2,"title":"Q4 All-Hands Meeting Scheduled","published_at":"2024-12-01","pinned":1,"author":"manager1"}]'
_CATALOG = '[{"id":1,"name":"Laptop Pro X1","price":1299.99,"category":"Computers","in_stock":1},{"id":2,"name":"Monitor 4K UHD 27\\"","price":599.99,"category":"Monitors","in_stock":1}]'
_SHARED_FILES = '[{"id":1,"filename":"employee_handbook_2024.pdf","shared_with":"everyone","uploader":"admin"},{"id":2,"filename":"engineering_onboarding.pdf","shared_with":"engineering","uploader":"manager1"}]'
_ACTIVITY_ALICE = '[{"id":1,"action":"login","target":"session","timestamp":"2024-12-01 09:15:22"},{"id":2,"action":"view","target":"document/3","timestamp":"2024-12-01 09:20:11"}]'
_TICKETS_LIST = '[{"id":1,"subject":"VPN connection dropping","status":"open","priority":"medium","is_public":1,"creator":"alice"},{"id":6,"subject":"Printer on 3rd floor","status":"resolved","priority":"low","is_public":1,"creator":"bob"}]'
_TEAMS_LIST = '[{"department":"Engineering"},{"department":"External"},{"department":"IT"},{"department":"Sales"}]'
_TEAM_ENG = '{"department":"Engineering","members":[{"id":2,"username":"manager1","role":"manager"},{"id":3,"username":"alice","role":"user"}]}'


SFT_EXAMPLES = [

    # ================================================================
    # SKILL: Initial Reconnaissance — always enumerate users first
    # ================================================================

    {"obs": _obs(200, _reset_body(_TASK_IDOR)), "action": "GET /api/users @alice"},
    {"obs": _obs(200, _reset_body(_TASK_PRIVESC)), "action": "GET /api/users @alice"},
    {"obs": _obs(200, _reset_body(_TASK_FULL)), "action": "GET /api/users @alice"},
    {"obs": _obs(200, _reset_body(_TASK_IDOR)), "action": "GET /api/users @bob"},
    {"obs": _obs(200, _reset_body(_TASK_PRIVESC)), "action": "GET /api/users @guest"},

    # ================================================================
    # SKILL: After user list — explore own data to understand structure
    # ================================================================

    {"obs": _obs(200, _USERS_JSON, "[01] GET /api/users @alice -> 200 r=+0.100"), "action": "GET /api/orders @alice"},

    {"obs": _obs(200, _USERS_JSON, "[01] GET /api/users @alice -> 200 r=+0.100"), "action": "GET /api/documents @alice"},

    {"obs": _obs(200, _USERS_JSON,
        "[01] GET /api/users @bob -> 200 r=+0.100"),
     "action": "GET /api/orders @bob"},

    {"obs": _obs(200, _USERS_JSON,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/orders @alice -> 200 r=+0.100"),
     "action": "GET /api/documents @alice"},

    {"obs": _obs(200, _USERS_JSON,
        "[01] GET /api/users @alice -> 200 r=+0.100"),
     "action": "GET /api/reports @alice"},

    {"obs": _obs(200, _USERS_JSON,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/orders @alice -> 200 r=+0.100\n[03] GET /api/documents @alice -> 200 r=+0.050"),
     "action": "GET /api/reports @alice"},

    {"obs": _obs(200, _USERS_JSON,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/orders @alice -> 200 r=+0.100\n[03] GET /api/documents @alice -> 200 r=+0.050\n[04] GET /api/reports @alice -> 200 r=+0.800"),
     "action": "GET /api/admin/config @alice"},

    # ================================================================
    # SKILL: Horizontal IDOR — orders (core vulnerability)
    # ================================================================

    {"obs": _obs(200, _ALICE_ORDERS,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/orders @alice -> 200 r=+0.100"),
     "action": "GET /api/orders @bob"},

    {"obs": _obs(200, _BOB_ORDERS,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/orders @alice -> 200 r=+0.100\n[03] GET /api/orders @bob -> 200 r=+0.100"),
     "action": "GET /api/orders/3 @alice"},

    {"obs": _obs(200, _ALICE_ORDERS,
        "[01] GET /api/users @alice -> 200 r=+0.100"),
     "action": "GET /api/orders/3 @alice"},

    {"obs": _obs(200, _ORDER3_DETAIL,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/orders @alice -> 200 r=+0.100\n[03] GET /api/orders/3 @alice -> 200 r=+0.500"),
     "action": "GET /api/orders/4 @alice"},

    {"obs": _obs(200, _ORDER3_DETAIL,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/orders/3 @alice -> 200 r=+0.500"),
     "action": "GET /api/orders/5 @alice"},

    {"obs": _obs(200, _ORDER5_DETAIL,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/orders/3 @alice -> 200 r=+0.500\n[03] GET /api/orders/5 @alice -> 200 r=+1.000"),
     "action": "GET /api/orders/6 @alice"},

    {"obs": _obs(200, _ORDER4_DETAIL,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/orders @alice -> 200 r=+0.100\n[03] GET /api/orders/3 @alice -> 200 r=+0.500\n[04] GET /api/orders/4 @alice -> 200 r=+0.020"),
     "action": "GET /api/orders/5 @alice"},

    {"obs": _obs(200, _ALICE_ORDERS,
        "[01] GET /api/users @bob -> 200 r=+0.100\n[02] GET /api/orders @bob -> 200 r=+0.100"),
     "action": "GET /api/orders/1 @bob"},

    {"obs": _obs(200, _ORDER1_DETAIL,
        "[01] GET /api/users @bob -> 200 r=+0.100\n[02] GET /api/orders/1 @bob -> 200 r=+0.500"),
     "action": "GET /api/orders/2 @bob"},

    {"obs": _obs(200, _BOB_ORDERS,
        "[01] GET /api/users @guest -> 200 r=+0.100\n[02] GET /api/orders @guest -> 200 r=+0.100"),
     "action": "GET /api/orders/3 @guest"},

    {"obs": _obs(200, _ORDER3_DETAIL,
        "[01] GET /api/users @guest -> 200 r=+0.100\n[02] GET /api/orders/3 @guest -> 200 r=+0.500"),
     "action": "GET /api/orders/5 @guest"},

    # ================================================================
    # SKILL: Vertical Privesc — reports (manager-only data)
    # ================================================================

    {"obs": _obs(200, _REPORTS_LIST,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/reports @alice -> 200 r=+0.800"),
     "action": "GET /api/reports/1 @alice"},

    {"obs": _obs(200, _REPORT1_DETAIL,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/reports @alice -> 200 r=+0.800\n[03] GET /api/reports/1 @alice -> 200 r=+0.020"),
     "action": "GET /api/reports/2 @alice"},

    {"obs": _obs(200, _REPORT2_DETAIL,
        "[01] GET /api/reports @alice -> 200 r=+0.800\n[02] GET /api/reports/1 @alice -> 200 r=+0.020\n[03] GET /api/reports/2 @alice -> 200 r=+0.020"),
     "action": "GET /api/admin/config @alice"},

    {"obs": _obs(200, _REPORTS_LIST,
        "[01] GET /api/users @guest -> 200 r=+0.100\n[02] GET /api/reports @guest -> 200 r=+0.800"),
     "action": "GET /api/reports/2 @guest"},

    {"obs": _obs(200, _REPORTS_LIST,
        "[01] GET /api/users @bob -> 200 r=+0.100\n[02] GET /api/reports @bob -> 200 r=+0.800"),
     "action": "GET /api/admin/config @bob"},

    {"obs": _obs(200, _USERS_JSON,
        "[01] GET /api/users @alice -> 200 r=+0.100"),
     "action": "GET /api/reports @guest"},

    {"obs": _obs(200, _REPORTS_LIST,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/reports @alice -> 200 r=+0.800"),
     "action": "GET /api/admin/config @guest"},

    # ================================================================
    # SKILL: Vertical Privesc — admin endpoints
    # ================================================================

    {"obs": _obs(200, _ADMIN_CONFIG,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/admin/config @alice -> 200 r=+1.000"),
     "action": "GET /api/admin/config @guest"},

    {"obs": _obs(200, _ADMIN_CONFIG,
        "[01] GET /api/admin/config @alice -> 200 r=+1.000\n[02] GET /api/admin/config @guest -> 200 r=+0.020"),
     "action": "GET /api/admin/users @alice"},

    {"obs": _obs(403, _ADMIN_USERS_403,
        "[01] GET /api/admin/config @alice -> 200 r=+1.000\n[02] GET /api/admin/users @alice -> 403 r=+0.100"),
     "action": "GET /api/admin/users @guest"},

    {"obs": _obs(403, _ADMIN_USERS_403,
        "[01] GET /api/admin/config @alice -> 200 r=+1.000\n[02] GET /api/admin/users @alice -> 403 r=+0.100\n[03] GET /api/admin/users @guest -> 403 r=+0.020"),
     "action": "DELETE /api/admin/users/5 @alice"},

    {"obs": _obs(403, _ADMIN_USERS_403,
        "[01] GET /api/admin/config @guest -> 200 r=+1.000\n[02] DELETE /api/admin/users/5 @alice -> 403 r=+0.020"),
     "action": "GET /api/reports @alice"},

    {"obs": _obs(200, _ADMIN_CONFIG,
        "[01] GET /api/users @guest -> 200 r=+0.100\n[02] GET /api/reports @guest -> 200 r=+0.800\n[03] GET /api/admin/config @guest -> 200 r=+1.000"),
     "action": "GET /api/admin/users @guest"},

    {"obs": _obs(200, _ADMIN_CONFIG,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/admin/config @alice -> 200 r=+1.000"),
     "action": "GET /api/admin/users @alice"},

    {"obs": _obs(200, _USERS_JSON,
        "[01] GET /api/users @alice -> 200 r=+0.100"),
     "action": "GET /api/admin/config @guest"},

    # ================================================================
    # SKILL: False Positive Recognition — public endpoints, move on
    # ================================================================

    {"obs": _obs(200, _ANNOUNCEMENTS,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/announcements @alice -> 200 r=+0.020"),
     "action": "GET /api/orders @alice"},

    {"obs": _obs(200, _CATALOG,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/catalog @alice -> 200 r=+0.020"),
     "action": "GET /api/orders @alice"},

    {"obs": _obs(200, _SHARED_FILES,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/shared-files @alice -> 200 r=+0.020"),
     "action": "GET /api/orders @alice"},

    {"obs": _obs(200, _ACTIVITY_ALICE,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/activity @alice -> 200 r=+0.020"),
     "action": "GET /api/orders @alice"},

    {"obs": _obs(200, _TICKETS_LIST,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/tickets @alice -> 200 r=+0.020"),
     "action": "GET /api/orders @alice"},

    {"obs": _obs(200, _TEAM_ENG,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/teams/Engineering @alice -> 200 r=+0.020"),
     "action": "GET /api/orders @alice"},

    {"obs": _obs(200, _TEAMS_LIST,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/teams @alice -> 200 r=+0.020"),
     "action": "GET /api/reports @alice"},

    {"obs": _obs(200, _ANNOUNCEMENTS,
        "[01] GET /api/users @guest -> 200 r=+0.100\n[02] GET /api/announcements @guest -> 200 r=+0.020"),
     "action": "GET /api/reports @guest"},

    {"obs": _obs(200, _CATALOG,
        "[01] GET /api/users @guest -> 200 r=+0.100\n[02] GET /api/catalog @guest -> 200 r=+0.020\n[03] GET /api/announcements @guest -> 200 r=+0.020"),
     "action": "GET /api/admin/config @guest"},

    {"obs": _obs(200, _SHARED_FILES,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/shared-files @alice -> 200 r=+0.020\n[03] GET /api/announcements @alice -> 200 r=+0.020"),
     "action": "GET /api/reports @alice"},

    # ================================================================
    # SKILL: Error Code Interpretation — adjust strategy, don't repeat
    # ================================================================

    {"obs": _obs(403, _ADMIN_USERS_403,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/admin/users @alice -> 403 r=+0.100"),
     "action": "GET /api/admin/config @alice"},

    {"obs": _obs(404, _NOT_FOUND_404,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/orders/10 @alice -> 404 r=-0.050"),
     "action": "GET /api/orders/3 @alice"},

    {"obs": _obs(404, _USER_NOT_FOUND_404,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/users/99 @alice -> 404 r=-0.050"),
     "action": "GET /api/users/1 @alice"},

    {"obs": _obs(404, _DOC_NOT_FOUND_404,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/documents/1 @alice -> 404 r=-0.050"),
     "action": "GET /api/documents @alice"},

    {"obs": _obs(403, _TICKET_DENIED_403,
        "[01] GET /api/tickets @alice -> 200 r=+0.020\n[02] GET /api/tickets/4 @alice -> 403 r=+0.020"),
     "action": "GET /api/orders @alice"},

    {"obs": _obs(404, _NOT_FOUND_404,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/orders @alice -> 200 r=+0.100\n[03] GET /api/orders/7 @alice -> 404 r=-0.050"),
     "action": "GET /api/orders/3 @alice"},

    {"obs": _obs(404, _NOT_FOUND_404,
        "[01] GET /api/orders/8 @bob -> 404 r=-0.050"),
     "action": "GET /api/users @bob"},

    {"obs": _obs(403, _ADMIN_USERS_403,
        "[01] GET /api/admin/users @guest -> 403 r=+0.100"),
     "action": "GET /api/admin/config @guest"},

    # ================================================================
    # SKILL: Cross-Account Comparison — test same endpoint, different accounts
    # ================================================================

    {"obs": _obs(200, _ALICE_ORDERS,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/orders @alice -> 200 r=+0.100"),
     "action": "GET /api/orders @bob"},

    {"obs": _obs(200, _ALICE_DOCS,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/documents @alice -> 200 r=+0.050"),
     "action": "GET /api/documents @bob"},

    {"obs": _obs(200, _REPORTS_LIST,
        "[01] GET /api/reports @manager1 -> 200 r=+0.050"),
     "action": "GET /api/reports @alice"},

    {"obs": _obs(200, _ADMIN_CONFIG,
        "[01] GET /api/admin/config @alice -> 200 r=+1.000"),
     "action": "GET /api/admin/config @guest"},

    {"obs": _obs(200, _ACTIVITY_ALICE,
        "[01] GET /api/activity @alice -> 200 r=+0.020"),
     "action": "GET /api/activity @bob"},

    # ================================================================
    # SKILL: Systematic Coverage — after finding one vuln, keep looking
    # ================================================================

    {"obs": _obs(200, _ORDER3_DETAIL,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/orders @alice -> 200 r=+0.100\n[03] GET /api/orders/3 @alice -> 200 r=+0.500"),
     "action": "GET /api/reports @alice"},

    {"obs": _obs(200, _REPORTS_LIST,
        "[01] GET /api/orders/3 @alice -> 200 r=+0.500\n[02] GET /api/reports @alice -> 200 r=+0.800"),
     "action": "GET /api/admin/config @alice"},

    {"obs": _obs(200, _ADMIN_CONFIG,
        "[01] GET /api/orders/3 @alice -> 200 r=+0.500\n[02] GET /api/reports @alice -> 200 r=+0.800\n[03] GET /api/admin/config @alice -> 200 r=+1.000"),
     "action": "GET /api/admin/users @alice"},

    {"obs": _obs(200, _USERS_JSON,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/orders @alice -> 200 r=+0.100"),
     "action": "GET /api/orders/3 @alice"},

    {"obs": _obs(200, _ALICE_ORDERS,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/orders @alice -> 200 r=+0.100"),
     "action": "GET /api/orders/3 @alice"},

    {"obs": _obs(200, _BOB_DOCS,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/documents @bob -> 200 r=+0.020"),
     "action": "GET /api/documents/4 @alice"},

    {"obs": _obs(200, _USERS_JSON,
        "[01] GET /api/users @alice -> 200 r=+0.100"),
     "action": "GET /api/orders @alice"},

    {"obs": _obs(200, _ORDER3_DETAIL,
        "[01] GET /api/orders/3 @alice -> 200 r=+0.500"),
     "action": "GET /api/orders/5 @alice"},

    # ================================================================
    # SKILL: Advanced — admin's resources, user detail probing
    # ================================================================

    {"obs": _obs(200, _USERS_JSON,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/orders/3 @alice -> 200 r=+0.500"),
     "action": "GET /api/orders/5 @alice"},

    {"obs": _obs(200, _ORDER5_DETAIL,
        "[01] GET /api/orders/5 @bob -> 200 r=+1.000"),
     "action": "GET /api/orders/6 @bob"},

    {"obs": _obs(200, _ORDER6_DETAIL,
        "[01] GET /api/orders/5 @alice -> 200 r=+1.000\n[02] GET /api/orders/6 @alice -> 200 r=+0.020"),
     "action": "GET /api/reports @alice"},

    {"obs": _obs(200, '{"id":3,"username":"alice","role":"user","department":"Engineering"}',
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/users/3 @bob -> 200 r=+0.050"),
     "action": "GET /api/users/1 @alice"},

    {"obs": _obs(200, '{"id":1,"username":"admin","role":"admin","department":"IT"}',
        "[01] GET /api/users/1 @alice -> 200 r=+0.020"),
     "action": "GET /api/orders/5 @alice"},

    {"obs": _obs(403, _ADMIN_USERS_403,
        "[01] GET /api/admin/config @alice -> 200 r=+1.000\n[02] DELETE /api/admin/users/5 @alice -> 403 r=+0.020"),
     "action": "GET /api/reports @alice"},

    {"obs": _obs(200, _REPORTS_LIST,
        "[01] GET /api/users @alice -> 200 r=+0.100\n[02] GET /api/orders/3 @alice -> 200 r=+0.500\n[03] GET /api/reports @alice -> 200 r=+0.800"),
     "action": "GET /api/admin/config @guest"},
]


def get_sft_conversations():
    convos = []
    for ex in SFT_EXAMPLES:
        convos.append([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": ex["obs"]},
            {"role": "assistant", "content": ex["action"]},
        ])
    return convos
