# TaskFlow

TaskFlow is a minimal full-stack project management app for creating projects, assigning tasks, and tracking progress with Admin/Member role-based access control.

## Features

- Signup and login with signed bearer sessions
- Admin and Member roles
- Project creation and team membership management
- Task creation, assignment, status updates, due dates, and delete controls
- Dashboard totals for projects, tasks, completed work, and overdue tasks
- REST APIs backed by SQLite relationships and validation

## Demo Accounts

- Admin: `admin@taskflow.test` / `password123`
- Member: `member@taskflow.test` / `password123`

The first seeded user is an admin. New signups become members after an admin exists.

## Local Setup

```bash
python app.py
```

Open `http://localhost:8000`.

Run the end-to-end smoke test:

```bash
python smoke_test.py
```

## REST API

- `POST /api/auth/signup`
- `POST /api/auth/login`
- `GET /api/me`
- `GET /api/users`
- `GET /api/dashboard`
- `GET /api/projects`
- `POST /api/projects`
- `POST /api/projects/:id/members`
- `GET /api/tasks`
- `POST /api/tasks`
- `PATCH /api/tasks/:id`
- `DELETE /api/tasks/:id`

Authenticated requests use:

```http
Authorization: Bearer <token>
```

## Role-Based Access

Admins can create projects, add team members, create tasks, assign tasks, update task status, and delete tasks.

Members can see projects they belong to, create tasks inside their projects, and update only tasks assigned to them.

## Database

SQLite tables:

- `users`
- `projects`
- `project_members`
- `tasks`

Relationships use foreign keys, including project members, task assignees, and task creators.

## Railway Deployment

1. Push this folder to GitHub.
2. Create a new Railway project from the GitHub repo.
3. Set environment variables:
   - `SESSION_SECRET`: any long random string
   - `DATABASE_PATH`: optional, defaults to `taskflow.sqlite3`
4. Railway will run the `Procfile` command:

```bash
python app.py
```

5. Open the generated Railway domain and test login with the demo accounts.

For a production-grade version, use Railway PostgreSQL or Supabase Postgres/Auth instead of local SQLite persistence.

## Submission Checklist

- Live URL: paste your Railway deployment URL
- GitHub repo: paste your repository URL
- README: this file
- Demo video: record 2-5 minutes showing login, admin project creation, team member assignment, task creation, status update, and member permissions
