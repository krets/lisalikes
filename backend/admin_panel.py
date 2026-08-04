def render_page(admin_path: str) -> str:
    base = f"/api/{admin_path}"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<link rel="icon" type="image/svg+xml" href="/favicon.svg" />
<title>Admin</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ background: #0a0a0f; color: #e5e5e5; font-family: system-ui, sans-serif; margin: 0; padding: 2rem; }}
  h1 {{ font-size: 1.25rem; margin: 0 0 1.5rem; }}
  .card {{ background: #16161d; border: 1px solid #2a2a35; border-radius: 10px; padding: 1rem 1.25rem; margin-bottom: 1rem; max-width: 720px; }}
  .card h2 {{ font-size: 0.95rem; margin: 0 0 0.75rem; color: #9a9aa5; text-transform: uppercase; letter-spacing: 0.04em; }}
  input {{ background: #0a0a0f; border: 1px solid #2a2a35; color: #e5e5e5; border-radius: 6px; padding: 0.45rem 0.6rem; font-size: 0.9rem; }}
  button {{ background: #1DB954; color: #04120a; border: none; border-radius: 6px; padding: 0.45rem 0.9rem; font-size: 0.9rem; font-weight: 600; cursor: pointer; }}
  button.secondary {{ background: #2a2a35; color: #e5e5e5; }}
  button.danger {{ background: #4a2020; color: #ff9b9b; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
  th, td {{ text-align: left; padding: 0.4rem 0.5rem; border-bottom: 1px solid #2a2a35; }}
  th {{ color: #9a9aa5; font-weight: 500; }}
  .row {{ display: flex; gap: 0.5rem; align-items: center; }}
  .muted {{ color: #9a9aa5; font-size: 0.85rem; }}
  .err {{ color: #ff9b9b; font-size: 0.8rem; }}
  .status-active {{ color: #1DB954; }}
  .status-revoked, .status-expired {{ color: #9a9aa5; }}
  a {{ color: #1DB954; }}
  #login {{ max-width: 320px; margin-top: 4rem; }}
</style>
</head>
<body>

<div id="login">
  <h1>Admin login</h1>
  <div class="card">
    <div class="row">
      <input id="secret" type="password" placeholder="Admin secret" style="flex:1" />
      <button onclick="login()">Log in</button>
    </div>
    <p id="loginError" class="err"></p>
  </div>
</div>

<div id="dashboard" style="display:none">
  <div class="row" style="justify-content: space-between; max-width: 720px;">
    <h1>LisaLikes Admin</h1>
    <button class="secondary" onclick="logout()">Log out</button>
  </div>

  <div class="card">
    <h2>Sync status</h2>
    <p id="syncSummary" class="muted"></p>
    <p id="syncErr" class="err"></p>
  </div>

  <div class="card">
    <h2>Target playlist</h2>
    <div class="row">
      <input id="playlistId" placeholder="Spotify playlist id" style="flex:1" />
      <button onclick="savePlaylist()">Save</button>
    </div>
    <p id="playlistName" class="muted"></p>
    <p class="muted">Spotify: <span id="spotifyLinked"></span> —
      <a href="{base}/spotify/authorize" target="_blank" rel="noopener">relink</a>
    </p>
  </div>

  <div class="card">
    <h2>Send invite</h2>
    <div class="row">
      <input id="inviteEmail" type="email" placeholder="email@example.com" style="flex:1" />
      <button onclick="sendInvite()">Send</button>
    </div>
    <p id="inviteMsg" class="muted"></p>
  </div>

  <div class="card">
    <h2>Invites</h2>
    <p id="inviteCounts" class="muted"></p>
    <table>
      <thead><tr><th>Email</th><th>Created</th><th>Expires</th><th>Last seen</th><th>Status</th><th></th></tr></thead>
      <tbody id="invitesBody"></tbody>
    </table>
  </div>

  <div class="card">
    <h2>Recent errors</h2>
    <table>
      <thead><tr><th>When</th><th>Message</th></tr></thead>
      <tbody id="errorsBody"></tbody>
    </table>
  </div>
</div>

<script>
const BASE = "{base}";

function fmt(ts) {{
  if (!ts) return "—";
  return new Date(Number(ts) * 1000).toLocaleString();
}}

async function api(path, opts) {{
  return fetch(BASE + path, {{
    credentials: "include",
    headers: {{ "Content-Type": "application/json" }},
    ...opts,
  }});
}}

async function adminApi(path, opts) {{
  return fetch("/api/admin" + path, {{
    credentials: "include",
    headers: {{ "Content-Type": "application/json" }},
    ...opts,
  }});
}}

async function login() {{
  const secret = document.getElementById("secret").value;
  const res = await api("/login", {{ method: "POST", body: JSON.stringify({{ secret }}) }});
  if (!res.ok) {{
    document.getElementById("loginError").textContent = "Invalid secret.";
    return;
  }}
  boot();
}}

async function logout() {{
  await api("/logout", {{ method: "POST" }});
  location.reload();
}}

async function loadStatus() {{
  const res = await adminApi("/status");
  if (!res.ok) return false;
  const s = await res.json();
  document.getElementById("syncSummary").textContent =
    `${{s.sync_status}} — last ingest ${{fmt(s.last_ingest_time)}}, last publish ${{fmt(s.last_publish_time)}}`;
  document.getElementById("syncErr").textContent =
    s.sync_error ? `[${{fmt(s.sync_error_time)}}] ${{s.sync_error}}` : "";
  document.getElementById("playlistId").value = s.target_playlist_id || "";
  document.getElementById("playlistName").textContent = s.target_playlist_name || "No playlist name cached";
  document.getElementById("spotifyLinked").textContent = s.spotify_linked ? "linked" : "not linked";
  return true;
}}

async function savePlaylist() {{
  const playlist_id = document.getElementById("playlistId").value.trim();
  await adminApi("/target-playlist", {{ method: "POST", body: JSON.stringify({{ playlist_id }}) }});
  await loadStatus();
}}

async function sendInvite() {{
  const email = document.getElementById("inviteEmail").value.trim();
  if (!email) return;
  const msgEl = document.getElementById("inviteMsg");
  msgEl.textContent = "Sending...";
  const res = await adminApi("/invite", {{ method: "POST", body: JSON.stringify({{ email }}) }});
  msgEl.textContent = res.ok ? `Invite sent to ${{email}}.` : "Failed to send invite.";
  document.getElementById("inviteEmail").value = "";
  await loadInvites();
}}

async function loadInvites() {{
  const res = await api("/invites");
  if (!res.ok) return;
  const invites = await res.json();
  const now = Date.now();
  const thirtyDaysAgo = now - 30 * 24 * 60 * 60 * 1000;
  const active = invites.filter(i => i.status === "active");
  const activeSessions = active.filter(i => i.last_seen_at && Number(i.last_seen_at) * 1000 > thirtyDaysAgo);
  document.getElementById("inviteCounts").textContent =
    `${{active.length}} active invite(s) — ${{activeSessions.length}} active session(s) in the last 30 days`;

  const body = document.getElementById("invitesBody");
  body.innerHTML = "";
  for (const i of invites) {{
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${{i.email || ""}}</td>
      <td>${{fmt(i.created_at)}}</td>
      <td>${{fmt(i.expires_at)}}</td>
      <td>${{fmt(i.last_seen_at)}}</td>
      <td class="status-${{i.status}}">${{i.status}}</td>
      <td>${{i.status === "active" ? `<button class="danger" data-jti="${{i.jti}}">Revoke</button>` : ""}}</td>
    `;
    const btn = tr.querySelector("button");
    if (btn) btn.addEventListener("click", () => revokeInvite(i.jti));
    body.appendChild(tr);
  }}
}}

async function revokeInvite(jti) {{
  await api(`/invites/${{jti}}/revoke`, {{ method: "POST" }});
  await loadInvites();
}}

async function loadErrors() {{
  const res = await api("/errors");
  if (!res.ok) return;
  const errors = await res.json();
  const body = document.getElementById("errorsBody");
  body.innerHTML = "";
  for (const e of errors) {{
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${{fmt(e.occurred_at)}}</td><td>${{e.message}}</td>`;
    body.appendChild(tr);
  }}
  if (!errors.length) {{
    body.innerHTML = `<tr><td colspan="2" class="muted">No errors recorded.</td></tr>`;
  }}
}}

async function boot() {{
  const ok = await loadStatus();
  if (!ok) {{
    document.getElementById("login").style.display = "block";
    document.getElementById("dashboard").style.display = "none";
    return;
  }}
  document.getElementById("login").style.display = "none";
  document.getElementById("dashboard").style.display = "block";
  await loadInvites();
  await loadErrors();
}}

boot();
</script>
</body>
</html>"""
