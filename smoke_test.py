import json
import os
import tempfile
import threading
import time
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

import app


def request(method, path, token=None, payload=None):
    conn = HTTPConnection("127.0.0.1", 8765, timeout=10)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(payload).encode() if payload is not None else None
    conn.request(method, path, body=body, headers=headers)
    res = conn.getresponse()
    data = json.loads(res.read().decode())
    conn.close()
    if res.status >= 400:
        raise AssertionError(f"{method} {path} failed: {res.status} {data}")
    return data


def main():
    temp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    temp.close()
    app.DB_PATH = Path(temp.name)
    app.init_db()
    server = ThreadingHTTPServer(("127.0.0.1", 8765), app.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        admin = request("POST", "/api/auth/login", payload={"email": "admin@taskflow.test", "password": "password123"})
        admin_token = admin["token"]
        project = request("POST", "/api/projects", admin_token, {"name": "Smoke Project", "description": "End-to-end check"})
        request("POST", f"/api/projects/{project['id']}/members", admin_token, {"user_id": 2})
        task = request(
            "POST",
            "/api/tasks",
            admin_token,
            {
                "project_id": project["id"],
                "title": "Smoke task",
                "assignee_id": 2,
                "status": "todo",
                "due_date": "2026-05-26",
            },
        )

        member = request("POST", "/api/auth/login", payload={"email": "member@taskflow.test", "password": "password123"})
        request("PATCH", f"/api/tasks/{task['id']}", member["token"], {"status": "in_progress"})
        dashboard = request("GET", "/api/dashboard", admin_token)
        assert dashboard["projects"] == 1
        assert dashboard["tasks"] == 1
        assert dashboard["overdue"] == 1

        print("Smoke test passed: auth, RBAC, projects, members, tasks, and dashboard work.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        for _ in range(5):
            try:
                os.unlink(app.DB_PATH)
                break
            except PermissionError:
                time.sleep(0.2)


if __name__ == "__main__":
    main()
