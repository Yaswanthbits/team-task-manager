import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from datetime import date, datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
DB_PATH = Path(os.environ.get("DATABASE_PATH", BASE_DIR / "taskflow.sqlite3"))
SECRET = os.environ.get("SESSION_SECRET", "dev-secret-change-on-railway").encode()
STATUSES = {"todo", "in_progress", "review", "done"}
ROLES = {"admin", "member"}


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('admin', 'member')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                owner_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS project_members (
                project_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (project_id, user_id),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                assignee_id INTEGER,
                status TEXT NOT NULL DEFAULT 'todo' CHECK (status IN ('todo', 'in_progress', 'review', 'done')),
                due_date TEXT,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (assignee_id) REFERENCES users(id) ON DELETE SET NULL,
                FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )
        admin = conn.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1").fetchone()
        if not admin:
            conn.execute(
                "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
                ("Demo Admin", "admin@taskflow.test", hash_password("password123"), "admin"),
            )
            conn.execute(
                "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
                ("Demo Member", "member@taskflow.test", hash_password("password123"), "member"),
            )


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return f"{salt}${digest.hex()}"


def verify_password(password, stored):
    try:
        salt, digest = stored.split("$", 1)
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
        return hmac.compare_digest(candidate, digest)
    except ValueError:
        return False


def b64(data):
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def sign(payload):
    body = b64(payload)
    signature = hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def unsign(token):
    try:
        body, signature = token.split(".", 1)
        expected = hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


def public_user(row):
    return {"id": row["id"], "name": row["name"], "email": row["email"], "role": row["role"]}


def parse_body(handler):
    length = int(handler.headers.get("Content-Length", "0"))
    if length == 0:
        return {}
    try:
        return json.loads(handler.rfile.read(length).decode())
    except json.JSONDecodeError:
        raise ValueError("Request body must be valid JSON.")


def validate_email(email):
    return isinstance(email, str) and "@" in email and "." in email.split("@")[-1]


def require_fields(data, fields):
    missing = [field for field in fields if not str(data.get(field, "")).strip()]
    if missing:
        raise ValueError(f"Missing required field(s): {', '.join(missing)}.")


def is_project_member(conn, project_id, user_id):
    row = conn.execute(
        "SELECT 1 FROM project_members WHERE project_id = ? AND user_id = ?",
        (project_id, user_id),
    ).fetchone()
    return bool(row)


def can_access_project(conn, user, project_id):
    if user["role"] == "admin":
        return True
    return is_project_member(conn, project_id, user["id"])


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        clean = urlparse(path).path
        if clean.startswith("/api/"):
            return str(PUBLIC_DIR / "index.html")
        if clean == "/":
            clean = "/index.html"
        return str(PUBLIC_DIR / clean.lstrip("/"))

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def json(self, status, payload):
        encoded = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def error_json(self, status, message):
        self.json(status, {"error": message})

    def current_user(self, conn):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return None
        payload = unsign(auth.removeprefix("Bearer ").strip())
        if not payload:
            return None
        row = conn.execute("SELECT * FROM users WHERE id = ?", (payload.get("sub"),)).fetchone()
        return public_user(row) if row else None

    def handle_api(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        method = self.command
        try:
            with db() as conn:
                if path == "/api/auth/signup" and method == "POST":
                    return self.signup(conn)
                if path == "/api/auth/login" and method == "POST":
                    return self.login(conn)

                user = self.current_user(conn)
                if not user:
                    return self.error_json(HTTPStatus.UNAUTHORIZED, "Login required.")

                if path == "/api/me" and method == "GET":
                    return self.json(HTTPStatus.OK, {"user": user})
                if path == "/api/users" and method == "GET":
                    return self.users(conn, user)
                if path == "/api/dashboard" and method == "GET":
                    return self.dashboard(conn, user)
                if path == "/api/projects" and method == "GET":
                    return self.projects(conn, user)
                if path == "/api/projects" and method == "POST":
                    return self.create_project(conn, user)
                if path == "/api/tasks" and method == "GET":
                    return self.tasks(conn, user)
                if path == "/api/tasks" and method == "POST":
                    return self.create_task(conn, user)
                if path.startswith("/api/projects/") and method == "POST":
                    return self.add_member(conn, user, path)
                if path.startswith("/api/tasks/") and method in {"PATCH", "DELETE"}:
                    return self.task_action(conn, user, path, method)
                return self.error_json(HTTPStatus.NOT_FOUND, "Endpoint not found.")
        except ValueError as exc:
            return self.error_json(HTTPStatus.BAD_REQUEST, str(exc))
        except sqlite3.IntegrityError:
            return self.error_json(HTTPStatus.BAD_REQUEST, "Invalid or duplicate relationship.")

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self.handle_api()
        return super().do_GET()

    def do_POST(self):
        return self.handle_api()

    def do_PATCH(self):
        return self.handle_api()

    def do_DELETE(self):
        return self.handle_api()

    def signup(self, conn):
        data = parse_body(self)
        require_fields(data, ["name", "email", "password"])
        email = data["email"].strip().lower()
        if not validate_email(email):
            raise ValueError("Enter a valid email address.")
        if len(data["password"]) < 8:
            raise ValueError("Password must be at least 8 characters.")
        role = data.get("role", "member")
        if role not in ROLES:
            raise ValueError("Role must be admin or member.")
        admin_exists = conn.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1").fetchone()
        role = "admin" if not admin_exists else "member"
        cursor = conn.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
            (data["name"].strip(), email, hash_password(data["password"]), role),
        )
        row = conn.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
        user = public_user(row)
        return self.json(HTTPStatus.CREATED, {"user": user, "token": sign({"sub": user["id"], "exp": time.time() + 86400})})

    def login(self, conn):
        data = parse_body(self)
        require_fields(data, ["email", "password"])
        row = conn.execute("SELECT * FROM users WHERE email = ?", (data["email"].strip().lower(),)).fetchone()
        if not row or not verify_password(data["password"], row["password_hash"]):
            return self.error_json(HTTPStatus.UNAUTHORIZED, "Invalid email or password.")
        user = public_user(row)
        return self.json(HTTPStatus.OK, {"user": user, "token": sign({"sub": user["id"], "exp": time.time() + 86400})})

    def users(self, conn, user):
        rows = conn.execute("SELECT id, name, email, role FROM users ORDER BY name").fetchall()
        return self.json(HTTPStatus.OK, {"users": [dict(row) for row in rows]})

    def projects(self, conn, user):
        if user["role"] == "admin":
            rows = conn.execute(
                """
                SELECT p.*, u.name AS owner_name,
                COUNT(DISTINCT pm.user_id) AS member_count,
                COUNT(DISTINCT t.id) AS task_count
                FROM projects p
                JOIN users u ON u.id = p.owner_id
                LEFT JOIN project_members pm ON pm.project_id = p.id
                LEFT JOIN tasks t ON t.project_id = p.id
                GROUP BY p.id
                ORDER BY p.created_at DESC
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT p.*, u.name AS owner_name,
                COUNT(DISTINCT pm.user_id) AS member_count,
                COUNT(DISTINCT t.id) AS task_count
                FROM projects p
                JOIN users u ON u.id = p.owner_id
                JOIN project_members mine ON mine.project_id = p.id AND mine.user_id = ?
                LEFT JOIN project_members pm ON pm.project_id = p.id
                LEFT JOIN tasks t ON t.project_id = p.id
                GROUP BY p.id
                ORDER BY p.created_at DESC
                """,
                (user["id"],),
            ).fetchall()
        return self.json(HTTPStatus.OK, {"projects": [dict(row) for row in rows]})

    def create_project(self, conn, user):
        if user["role"] != "admin":
            return self.error_json(HTTPStatus.FORBIDDEN, "Only admins can create projects.")
        data = parse_body(self)
        require_fields(data, ["name"])
        cursor = conn.execute(
            "INSERT INTO projects (name, description, owner_id) VALUES (?, ?, ?)",
            (data["name"].strip(), data.get("description", "").strip(), user["id"]),
        )
        conn.execute("INSERT INTO project_members (project_id, user_id) VALUES (?, ?)", (cursor.lastrowid, user["id"]))
        return self.json(HTTPStatus.CREATED, {"id": cursor.lastrowid})

    def add_member(self, conn, user, path):
        if user["role"] != "admin":
            return self.error_json(HTTPStatus.FORBIDDEN, "Only admins can manage project teams.")
        parts = path.split("/")
        if len(parts) != 5 or parts[4] != "members":
            return self.error_json(HTTPStatus.NOT_FOUND, "Endpoint not found.")
        project_id = int(parts[3])
        data = parse_body(self)
        user_id = int(data.get("user_id", 0))
        conn.execute("INSERT INTO project_members (project_id, user_id) VALUES (?, ?)", (project_id, user_id))
        return self.json(HTTPStatus.CREATED, {"ok": True})

    def tasks(self, conn, user):
        clause = ""
        params = []
        if user["role"] != "admin":
            clause = "WHERE (t.assignee_id = ? OR pm.user_id = ?)"
            params = [user["id"], user["id"]]
        rows = conn.execute(
            f"""
            SELECT t.*, p.name AS project_name, u.name AS assignee_name, c.name AS created_by_name
            FROM tasks t
            JOIN projects p ON p.id = t.project_id
            JOIN project_members pm ON pm.project_id = p.id
            LEFT JOIN users u ON u.id = t.assignee_id
            JOIN users c ON c.id = t.created_by
            {clause}
            GROUP BY t.id
            ORDER BY COALESCE(t.due_date, '9999-12-31'), t.created_at DESC
            """,
            params,
        ).fetchall()
        return self.json(HTTPStatus.OK, {"tasks": [dict(row) for row in rows]})

    def create_task(self, conn, user):
        data = parse_body(self)
        require_fields(data, ["project_id", "title"])
        project_id = int(data["project_id"])
        if user["role"] != "admin" and not can_access_project(conn, user, project_id):
            return self.error_json(HTTPStatus.FORBIDDEN, "You can only add tasks to your projects.")
        status = data.get("status", "todo")
        if status not in STATUSES:
            raise ValueError("Invalid task status.")
        due_date = data.get("due_date") or None
        if due_date:
            datetime.strptime(due_date, "%Y-%m-%d")
        assignee_id = data.get("assignee_id") or None
        if assignee_id and not is_project_member(conn, project_id, int(assignee_id)):
            raise ValueError("Assignee must be a member of the selected project.")
        cursor = conn.execute(
            """
            INSERT INTO tasks (project_id, title, description, assignee_id, status, due_date, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (project_id, data["title"].strip(), data.get("description", "").strip(), assignee_id, status, due_date, user["id"]),
        )
        return self.json(HTTPStatus.CREATED, {"id": cursor.lastrowid})

    def task_action(self, conn, user, path, method):
        task_id = int(path.split("/")[3])
        task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return self.error_json(HTTPStatus.NOT_FOUND, "Task not found.")
        if user["role"] != "admin" and task["assignee_id"] != user["id"]:
            return self.error_json(HTTPStatus.FORBIDDEN, "Members can only update their assigned tasks.")
        if method == "DELETE":
            if user["role"] != "admin":
                return self.error_json(HTTPStatus.FORBIDDEN, "Only admins can delete tasks.")
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            return self.json(HTTPStatus.OK, {"ok": True})
        data = parse_body(self)
        status = data.get("status")
        if status not in STATUSES:
            raise ValueError("Invalid task status.")
        conn.execute("UPDATE tasks SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (status, task_id))
        return self.json(HTTPStatus.OK, {"ok": True})

    def dashboard(self, conn, user):
        project_filter = ""
        task_filter = ""
        params = []
        if user["role"] != "admin":
            project_filter = "JOIN project_members pm ON pm.project_id = p.id AND pm.user_id = ?"
            task_filter = "JOIN project_members pm ON pm.project_id = t.project_id AND pm.user_id = ?"
            params.append(user["id"])
        projects = conn.execute(f"SELECT COUNT(DISTINCT p.id) AS total FROM projects p {project_filter}", params).fetchone()["total"]
        task_rows = conn.execute(
            f"""
            SELECT t.status, COUNT(*) AS count
            FROM tasks t
            {task_filter}
            GROUP BY t.status
            """,
            params,
        ).fetchall()
        overdue = conn.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM tasks t
            {task_filter}
            WHERE t.status != 'done' AND t.due_date IS NOT NULL AND t.due_date < ?
            """,
            (*params, date.today().isoformat()),
        ).fetchone()["total"]
        by_status = {status: 0 for status in STATUSES}
        for row in task_rows:
            by_status[row["status"]] = row["count"]
        return self.json(HTTPStatus.OK, {"projects": projects, "tasks": sum(by_status.values()), "overdue": overdue, "by_status": by_status})


def main():
    init_db()
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"TaskFlow running on http://localhost:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
@app.route("/")
def home():
    return "Task Manager App Running Successfully!"
