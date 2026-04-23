import json
import os
import socket
import tempfile
import threading
import time
from uuid import uuid4

import requests
from werkzeug.serving import make_server

from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import State

from models import IdorHuntAction, IdorHuntObservation
from server.target_app import create_app, init_db


ACCOUNT_TOKENS = {
    "alice":    "tok_alice_j3p",
    "bob":      "tok_bob_m2q",
    "manager1": "tok_mgr_k9m",
    "guest":    "tok_guest_q1r",
}

ACCOUNT_INFO = {
    "alice":    {"role": "user",    "department": "Engineering"},
    "bob":      {"role": "user",    "department": "Sales"},
    "manager1": {"role": "manager", "department": "Engineering"},
    "guest":    {"role": "guest",   "department": "External"},
}

MAX_STEPS = {
    "idor_horizontal": 15,
    "privesc": 20,
    "full_audit": 30,
}

ENDPOINTS = [
    "GET  /api/users",
    "GET  /api/users/<id>",
    "GET  /api/orders",
    "GET  /api/orders/<id>",
    "GET  /api/documents",
    "GET  /api/documents/<id>",
    "GET  /api/reports",
    "GET  /api/reports/<id>",
    "GET  /api/admin/config",
    "GET  /api/admin/users",
    "DELETE /api/admin/users/<id>",
]

TASK_DESCRIPTIONS = {
    "idor_horizontal": (
        "Test this corporate API for horizontal IDOR vulnerabilities. "
        "Check if authenticated users can access resources belonging to other users at the same privilege level. "
        "Try accessing other users' data through various endpoints."
    ),
    "privesc": (
        "Test this corporate API for vertical privilege escalation. "
        "Check if lower-privileged users (user, guest) can access endpoints or data "
        "that should be restricted to higher roles (manager, admin)."
    ),
    "full_audit": (
        "Perform a full access control audit of this corporate API. "
        "Find all broken access control vulnerabilities: "
        "horizontal IDOR (accessing other users' resources) and "
        "vertical privilege escalation (accessing higher-role endpoints). "
        "Test systematically across all accounts and endpoints."
    ),
}


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class IdorHuntEnvironment(Environment):
    SUPPORTS_CONCURRENT_SESSIONS = True

    def __init__(self):
        super().__init__()
        self._state = State(episode_id=str(uuid4()), step_count=0)
        self.done = False
        self.task_id = "idor_horizontal"
        self.cumulative_reward = 0.0
        self.findings = set()
        self.visited = set()

        self._db_file = None
        self._port = _free_port()
        self._flask_server = None
        self._flask_thread = None
        self._start_server()

    def _start_server(self):
        fd, self._db_file = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        init_db(self._db_file)
        flask_app = create_app(self._db_file)
        self._flask_app = flask_app
        self._flask_server = make_server("127.0.0.1", self._port, flask_app)
        self._flask_thread = threading.Thread(
            target=self._flask_server.serve_forever, daemon=True
        )
        self._flask_thread.start()
        for _ in range(50):
            try:
                requests.get(f"http://127.0.0.1:{self._port}/api/health", timeout=1)
                return
            except Exception:
                time.sleep(0.1)

    def _reinit_db(self):
        if self._db_file and os.path.exists(self._db_file):
            try:
                os.unlink(self._db_file)
            except OSError:
                pass
        fd, self._db_file = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        init_db(self._db_file)
        self._flask_app.config["DB_PATH"] = self._db_file

    def reset(self, task_id=None, **kwargs):
        self._state = State(episode_id=str(uuid4()), step_count=0)
        self.done = False
        self.task_id = task_id or "idor_horizontal"
        self.cumulative_reward = 0.0
        self.findings = set()
        self.visited = set()
        self._reinit_db()

        body = json.dumps({
            "app": "CorpAPI",
            "version": "2.1.0",
            "task": TASK_DESCRIPTIONS.get(self.task_id, ""),
            "endpoints": ENDPOINTS,
            "accounts": ACCOUNT_INFO,
            "note": "Use @account_name suffix to act as a specific account. Default: alice. Example: GET /api/orders @bob",
        })

        return IdorHuntObservation(
            status_code=200,
            body=body,
            done=False,
            reward=0.0,
        )

    def step(self, action):
        self._state.step_count += 1

        method = action.method.upper().strip()
        path = action.path.strip()
        body = (action.body or "").strip() or None
        account = (action.account or "alice").strip().lower()

        token = ACCOUNT_TOKENS.get(account)
        if not token:
            return IdorHuntObservation(
                status_code=400,
                body=json.dumps({"error": f"Unknown account: {account}. Available: {list(ACCOUNT_TOKENS.keys())}"}),
                done=False,
                reward=-0.1,
            )

        key = f"{method}:{path}:{body}:{account}"
        is_repeat = key in self.visited
        self.visited.add(key)

        try:
            url = f"http://127.0.0.1:{self._port}{path}"
            headers = {"Authorization": f"Bearer {token}"}
            if body:
                headers["Content-Type"] = "application/json"
            resp = requests.request(
                method, url, headers=headers,
                data=body, timeout=10, allow_redirects=True,
            )
            status = resp.status_code
            resp_body = resp.text[:5000]
        except Exception as exc:
            return IdorHuntObservation(
                status_code=503,
                body=json.dumps({"error": str(exc)}),
                done=False,
                reward=-0.1,
            )

        if is_repeat:
            return IdorHuntObservation(
                status_code=status, body=resp_body,
                done=self.done, reward=-0.1,
            )

        reward = self._compute_reward(method, path, status, resp_body, account)

        max_steps = MAX_STEPS.get(self.task_id, 15)
        if self._state.step_count >= max_steps and not self.done:
            self.done = True
            reward -= 0.5

        self.cumulative_reward += reward

        return IdorHuntObservation(
            status_code=status,
            body=resp_body,
            done=self.done,
            reward=round(reward, 3),
        )

    def _compute_reward(self, method, path, status, resp_body, account):
        account_role = ACCOUNT_INFO.get(account, {}).get("role", "user")
        reward = 0.0

        if status == 401:
            return -0.05
        if status == 404:
            return -0.05
        if status == 403:
            if "secure_endpoint_found" not in self.findings:
                self.findings.add("secure_endpoint_found")
                return 0.1
            return 0.02
        if status != 200:
            return 0.0

        if path == "/api/users" and "user_list" not in self.findings:
            self.findings.add("user_list")
            reward = 0.1

        elif path.startswith("/api/users/") and "user_detail" not in self.findings:
            self.findings.add("user_detail")
            reward = 0.05

        elif path == "/api/orders" and f"own_orders_{account}" not in self.findings:
            self.findings.add(f"own_orders_{account}")
            reward = 0.1

        elif path.startswith("/api/orders/") and status == 200:
            reward = self._check_orders_idor(resp_body, account)

        elif path == "/api/documents" and f"own_docs_{account}" not in self.findings:
            self.findings.add(f"own_docs_{account}")
            reward = 0.05

        elif path.startswith("/api/documents/") and status == 200:
            reward = 0.02

        elif path == "/api/reports" and status == 200:
            reward = self._check_reports_privesc(account_role)

        elif path.startswith("/api/reports/") and status == 200:
            reward = self._check_report_detail_privesc(resp_body, account_role)

        elif path == "/api/admin/config" and status == 200:
            reward = self._check_admin_config_privesc(account_role)

        elif path == "/api/admin/users" and status == 200:
            reward = 0.02

        else:
            reward = 0.02

        self._check_done()
        return reward

    def _check_orders_idor(self, resp_body, account):
        try:
            data = json.loads(resp_body)
            owner_id = data.get("user_id")
            account_user_ids = {"alice": 3, "bob": 4, "manager1": 2, "guest": 5}
            acting_uid = account_user_ids.get(account)
            if owner_id and acting_uid and owner_id != acting_uid:
                finding_key = f"orders_idor_{account}_accessed_{owner_id}"
                if finding_key not in self.findings:
                    self.findings.add(finding_key)
                    self.findings.add("orders_idor")
                    if owner_id == 1:
                        self.findings.add("orders_idor_admin")
                        return 1.0
                    return 0.5
                return 0.02
        except (json.JSONDecodeError, ValueError):
            pass
        if f"own_order_read_{account}" not in self.findings:
            self.findings.add(f"own_order_read_{account}")
            return 0.05
        return 0.02

    def _check_reports_privesc(self, account_role):
        if account_role in ("user", "guest"):
            if "reports_privesc" not in self.findings:
                self.findings.add("reports_privesc")
                return 0.8
            return 0.02
        if "reports_listed" not in self.findings:
            self.findings.add("reports_listed")
            return 0.05
        return 0.02

    def _check_report_detail_privesc(self, resp_body, account_role):
        if account_role in ("user", "guest"):
            if "reports_privesc" not in self.findings:
                self.findings.add("reports_privesc")
                return 0.8
            return 0.02
        if "report_detail_read" not in self.findings:
            self.findings.add("report_detail_read")
            return 0.05
        return 0.02

    def _check_admin_config_privesc(self, account_role):
        if account_role != "admin":
            if "admin_config_privesc" not in self.findings:
                self.findings.add("admin_config_privesc")
                return 1.0
            return 0.02
        return 0.05

    def _check_done(self):
        if self.task_id == "idor_horizontal":
            if "orders_idor" in self.findings:
                self.done = True
        elif self.task_id == "privesc":
            if "reports_privesc" in self.findings and "admin_config_privesc" in self.findings:
                self.done = True
        elif self.task_id == "full_audit":
            if all(k in self.findings for k in ("orders_idor", "reports_privesc", "admin_config_privesc")):
                self.done = True

    def get_grade(self):
        if self.task_id == "idor_horizontal":
            if "orders_idor_admin" in self.findings:
                return 0.99
            if "orders_idor" in self.findings:
                return 0.7
            if any(k.startswith("own_orders_") for k in self.findings):
                return 0.2
            if "user_list" in self.findings:
                return 0.1
            return 0.01

        if self.task_id == "privesc":
            found = sum(1 for k in ("reports_privesc", "admin_config_privesc") if k in self.findings)
            if found == 2:
                return 0.99
            if found == 1:
                return 0.5
            if "secure_endpoint_found" in self.findings:
                return 0.15
            if "user_list" in self.findings:
                return 0.1
            return 0.01

        if self.task_id == "full_audit":
            vulns = [k for k in ("orders_idor", "reports_privesc", "admin_config_privesc") if k in self.findings]
            count = len(vulns)
            if count == 3:
                return 0.99
            if count == 2:
                return 0.7
            if count == 1:
                return 0.4
            if any(k.startswith("own_") for k in self.findings):
                return 0.15
            if "user_list" in self.findings:
                return 0.1
            return 0.01

        return 0.01

    def close(self):
        if self._flask_server:
            try:
                self._flask_server.shutdown()
            except Exception:
                pass
        if self._db_file and os.path.exists(self._db_file):
            try:
                os.unlink(self._db_file)
            except OSError:
                pass

    @property
    def state(self):
        return self._state
