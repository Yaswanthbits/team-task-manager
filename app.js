const state = {
  token: localStorage.getItem("token"),
  user: JSON.parse(localStorage.getItem("user") || "null"),
  users: [],
  projects: [],
  tasks: [],
  dashboard: null,
};

const statuses = [
  ["todo", "To do"],
  ["in_progress", "In progress"],
  ["review", "Review"],
  ["done", "Done"],
];

const app = document.querySelector("#app");

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}),
      ...(options.headers || {}),
    },
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Something went wrong");
  return data;
}

function saveSession(payload) {
  state.token = payload.token;
  state.user = payload.user;
  localStorage.setItem("token", payload.token);
  localStorage.setItem("user", JSON.stringify(payload.user));
}

function logout() {
  localStorage.removeItem("token");
  localStorage.removeItem("user");
  state.token = null;
  state.user = null;
  renderAuth();
}

function statusLabel(value) {
  return statuses.find(([key]) => key === value)?.[1] || value;
}

function isOverdue(task) {
  return task.due_date && task.status !== "done" && task.due_date < new Date().toISOString().slice(0, 10);
}

function renderAuth(mode = "login") {
  app.innerHTML = `
    <section class="auth">
      <form class="auth-panel" id="auth-form">
        <div class="brand"><span class="mark">T</span><span>TaskFlow</span></div>
        <div>
          <h1>${mode === "login" ? "Login" : "Create account"}</h1>
          <p class="muted">Demo users: admin@taskflow.test / member@taskflow.test, password123</p>
        </div>
        <div class="form-grid">
          <label class="${mode === "login" ? "hidden" : ""}">Name
            <input name="name" value="New User" />
          </label>
          <label>Email
            <input name="email" type="email" value="${mode === "login" ? "admin@taskflow.test" : ""}" required />
          </label>
          <label>Password
            <input name="password" type="password" value="${mode === "login" ? "password123" : ""}" minlength="8" required />
          </label>
        </div>
        <div class="error" id="auth-error"></div>
        <button>${mode === "login" ? "Login" : "Sign up"}</button>
        <button class="secondary" type="button" id="switch-mode">${mode === "login" ? "Need an account?" : "Already have an account?"}</button>
      </form>
    </section>
  `;
  document.querySelector("#switch-mode").onclick = () => renderAuth(mode === "login" ? "signup" : "login");
  document.querySelector("#auth-form").onsubmit = async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = Object.fromEntries(form.entries());
    try {
      const data = await api(`/api/auth/${mode}`, { method: "POST", body: JSON.stringify(payload) });
      saveSession(data);
      await loadApp();
    } catch (error) {
      document.querySelector("#auth-error").textContent = error.message;
    }
  };
}

async function loadApp() {
  try {
    const [dashboard, users, projects, tasks] = await Promise.all([
      api("/api/dashboard"),
      api("/api/users"),
      api("/api/projects"),
      api("/api/tasks"),
    ]);
    state.dashboard = dashboard;
    state.users = users.users;
    state.projects = projects.projects;
    state.tasks = tasks.tasks;
    renderApp();
  } catch (error) {
    logout();
  }
}

function optionList(items, label = "name") {
  return items.map((item) => `<option value="${item.id}">${item[label]}</option>`).join("");
}

function renderApp() {
  const admin = state.user.role === "admin";
  app.innerHTML = `
    <section class="shell">
      <header class="topbar">
        <div class="brand"><span class="mark">T</span><span>TaskFlow</span></div>
        <div class="userbar">
          <span>${state.user.name}</span>
          <span class="role">${state.user.role}</span>
          <button class="secondary" id="logout">Logout</button>
        </div>
      </header>
      <div class="content">
        <section class="stats">
          <div class="stat"><strong>${state.dashboard.projects}</strong><span class="muted">Projects</span></div>
          <div class="stat"><strong>${state.dashboard.tasks}</strong><span class="muted">Tasks</span></div>
          <div class="stat"><strong>${state.dashboard.by_status.done || 0}</strong><span class="muted">Done</span></div>
          <div class="stat"><strong>${state.dashboard.overdue}</strong><span class="muted">Overdue</span></div>
        </section>
        <section class="split">
          <div class="grid">
            <section class="section ${admin ? "" : "hidden"}">
              <h2>Projects</h2>
              <form class="form-grid" id="project-form">
                <label>Project name <input name="name" required /></label>
                <label>Description <textarea name="description" rows="3"></textarea></label>
                <button>Create project</button>
                <div class="error" id="project-error"></div>
              </form>
            </section>
            <section class="section ${admin ? "" : "hidden"}">
              <h2>Team</h2>
              <form class="form-grid" id="member-form">
                <label>Project <select name="project_id">${optionList(state.projects)}</select></label>
                <label>User <select name="user_id">${optionList(state.users)}</select></label>
                <button>Add member</button>
                <div class="error" id="member-error"></div>
              </form>
            </section>
            <section class="section">
              <h2>New task</h2>
              <form class="form-grid" id="task-form">
                <label>Project <select name="project_id" required>${optionList(state.projects)}</select></label>
                <label>Title <input name="title" required /></label>
                <label>Description <textarea name="description" rows="3"></textarea></label>
                <div class="two">
                  <label>Assignee <select name="assignee_id"><option value="">Unassigned</option>${optionList(state.users)}</select></label>
                  <label>Status <select name="status">${statuses.map(([key, label]) => `<option value="${key}">${label}</option>`).join("")}</select></label>
                </div>
                <label>Due date <input name="due_date" type="date" /></label>
                <button>Create task</button>
                <div class="error" id="task-error"></div>
              </form>
            </section>
          </div>
          <div class="grid">
            <section class="section">
              <h2>Project overview</h2>
              <div class="cards">${state.projects.map(renderProject).join("") || `<p class="muted">No projects yet.</p>`}</div>
            </section>
            <section class="section">
              <h2>Tasks</h2>
              <div class="cards">${state.tasks.map(renderTask).join("") || `<p class="muted">No tasks yet.</p>`}</div>
            </section>
          </div>
        </section>
      </div>
    </section>
  `;
  document.querySelector("#logout").onclick = logout;
  wireForms();
}

function renderProject(project) {
  return `
    <article class="card">
      <div class="card-head">
        <h3>${project.name}</h3>
        <span class="pill">${project.task_count} tasks</span>
      </div>
      <p class="muted">${project.description || "No description"}</p>
      <div class="meta">
        <span>Owner: ${project.owner_name}</span>
        <span>${project.member_count} members</span>
      </div>
    </article>
  `;
}

function renderTask(task) {
  return `
    <article class="card">
      <div class="card-head">
        <h3>${task.title}</h3>
        <span class="pill ${task.status}">${statusLabel(task.status)}</span>
      </div>
      <p class="muted">${task.description || "No description"}</p>
      <div class="meta">
        <span>${task.project_name}</span>
        <span>Assigned: ${task.assignee_name || "Unassigned"}</span>
        ${task.due_date ? `<span>Due: ${task.due_date}</span>` : ""}
        ${isOverdue(task) ? `<span class="pill overdue">Overdue</span>` : ""}
      </div>
      <div class="task-actions">
        <select data-status="${task.id}">
          ${statuses.map(([key, label]) => `<option value="${key}" ${task.status === key ? "selected" : ""}>${label}</option>`).join("")}
        </select>
        <button data-update="${task.id}">Update</button>
        ${state.user.role === "admin" ? `<button class="danger" data-delete="${task.id}">Delete</button>` : ""}
      </div>
    </article>
  `;
}

function wireForms() {
  const projectForm = document.querySelector("#project-form");
  if (projectForm) {
    projectForm.onsubmit = async (event) => {
      event.preventDefault();
      await submitForm(event.currentTarget, "/api/projects", "#project-error");
    };
  }
  const memberForm = document.querySelector("#member-form");
  if (memberForm) {
    memberForm.onsubmit = async (event) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      const projectId = form.get("project_id");
      await submitForm(event.currentTarget, `/api/projects/${projectId}/members`, "#member-error");
    };
  }
  document.querySelector("#task-form").onsubmit = async (event) => {
    event.preventDefault();
    await submitForm(event.currentTarget, "/api/tasks", "#task-error");
  };
  document.querySelectorAll("[data-update]").forEach((button) => {
    button.onclick = async () => {
      const taskId = button.dataset.update;
      const status = document.querySelector(`[data-status="${taskId}"]`).value;
      await api(`/api/tasks/${taskId}`, { method: "PATCH", body: JSON.stringify({ status }) });
      await loadApp();
    };
  });
  document.querySelectorAll("[data-delete]").forEach((button) => {
    button.onclick = async () => {
      await api(`/api/tasks/${button.dataset.delete}`, { method: "DELETE" });
      await loadApp();
    };
  });
}

async function submitForm(form, path, errorSelector) {
  const error = document.querySelector(errorSelector);
  error.textContent = "";
  const payload = Object.fromEntries(new FormData(form).entries());
  Object.keys(payload).forEach((key) => {
    if (payload[key] === "") payload[key] = null;
  });
  try {
    await api(path, { method: "POST", body: JSON.stringify(payload) });
    form.reset();
    await loadApp();
  } catch (err) {
    error.textContent = err.message;
  }
}

if (state.token) {
  loadApp();
} else {
  renderAuth();
}
