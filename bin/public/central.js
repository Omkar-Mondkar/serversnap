/**
 * central.js — ServerSnap Central fleet dashboard
 * Single-page application: home (card grid) ↔ detail view
 * No frameworks; stdlib fetch + vanilla DOM.
 */

"use strict";

// ────────────────────────────────────────────────────────────────
// Constants
// ────────────────────────────────────────────────────────────────
const REFRESH_INTERVAL_SECS = 60;

// Session token key (sessionStorage) used as a cookie fallback when this
// page is embedded in a cross-origin <iframe> - see /login's inline script.
const AUTH_TOKEN_KEY = "sscentral_auth_token";

function authHeaders() {
  const token = sessionStorage.getItem(AUTH_TOKEN_KEY);
  return token ? { "X-Auth-Token": token } : {};
}

function handleAuthFailure() {
  sessionStorage.removeItem(AUTH_TOKEN_KEY);
  window.location.href = "/login";
}

// ────────────────────────────────────────────────────────────────
// DOM refs
// ────────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

const views = {
  home: $("view-home"),
  detail: $("view-detail"),
};

const els = {
  cardGrid: $("card-grid"),
  emptyState: $("empty-state"),
  statsBar: $("stats-bar"),
  countHealthy: $("count-healthy"),
  countStale: $("count-stale"),
  countUnknown: $("count-unknown"),
  countChanges: $("count-changes"),
  refreshDot: $("refresh-dot"),
  refreshCountdown: $("refresh-countdown"),
  loadingOverlay: $("loading-overlay"),
  toast: $("toast"),
  backBtn: $("back-btn"),
  fullDashBtn: $("full-dashboard-btn"),
  logoutBtn: $("logout-btn"),
  // Detail
  detailServerId: $("detail-server-id"),
  detailHostname: $("detail-hostname"),
  detailHealthBadge: $("detail-health-badge"),
  detailLastSeen: $("detail-last-seen"),
  changeChips: $("change-chips"),
  changedFilesList: $("changed-files-list"),
  snapshotMeta: $("snapshot-meta"),
  approvalHistory: $("approval-history-list"),
};

// ────────────────────────────────────────────────────────────────
// State
// ────────────────────────────────────────────────────────────────
let _servers = [];
let _refreshTimer = null;
let _countdownTimer = null;
let _countdown = REFRESH_INTERVAL_SECS;
let _currentView = "home";
let _toastTimer = null;

// ────────────────────────────────────────────────────────────────
// Utilities
// ────────────────────────────────────────────────────────────────

function timeAgo(isoString) {
  if (!isoString) return "—";
  const then = new Date(isoString);
  if (isNaN(then)) return "—";
  const diffSecs = Math.floor((Date.now() - then) / 1000);
  if (diffSecs < 5) return "just now";
  if (diffSecs < 60) return `${diffSecs}s ago`;
  const mins = Math.floor(diffSecs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function showLoading(on) {
  els.loadingOverlay.classList.toggle("visible", on);
}

function showToast(msg, isError = false) {
  clearTimeout(_toastTimer);
  els.toast.textContent = msg;
  els.toast.className = "toast visible" + (isError ? " toast--error" : "");
  _toastTimer = setTimeout(() => {
    els.toast.classList.remove("visible");
  }, 3500);
}

function setView(name) {
  _currentView = name;
  for (const [key, el] of Object.entries(views)) {
    el.hidden = key !== name;
  }
}

function pulseDot() {
  els.refreshDot.classList.remove("pulsing");
  // Force reflow to restart animation
  void els.refreshDot.offsetWidth;
  els.refreshDot.classList.add("pulsing");
  setTimeout(() => els.refreshDot.classList.remove("pulsing"), 1000);
}

// ────────────────────────────────────────────────────────────────
// Rendering: health badge
// ────────────────────────────────────────────────────────────────

function healthLabel(h) {
  return (
    { healthy: "Healthy", stale: "Stale", unknown: "Unknown" }[h] || "Unknown"
  );
}

function createHealthBadge(health) {
  const span = document.createElement("span");
  span.className = `health-badge health-${health}`;
  span.textContent = healthLabel(health);
  return span;
}

// ────────────────────────────────────────────────────────────────
// Rendering: change chips
// ────────────────────────────────────────────────────────────────

function buildChangeChips(summary, hasChanges) {
  if (!hasChanges || !summary) {
    const chip = document.createElement("span");
    chip.className = "change-chip change-chip--none";
    chip.textContent = "No changes";
    return [chip];
  }
  const specs = [
    { key: "added", label: "+{n} added", cls: "change-chip--added" },
    { key: "deleted", label: "-{n} deleted", cls: "change-chip--deleted" },
    { key: "modified", label: "~{n} modified", cls: "change-chip--modified" },
  ];
  const chips = [];
  for (const { key, label, cls } of specs) {
    const n = summary[key] ?? 0;
    if (n === 0) continue;
    const chip = document.createElement("span");
    chip.className = `change-chip ${cls}`;
    chip.textContent = label.replace("{n}", n);
    chips.push(chip);
  }
  if (chips.length === 0) {
    const chip = document.createElement("span");
    chip.className = "change-chip change-chip--none";
    chip.textContent = "No changes";
    chips.push(chip);
  }
  return chips;
}

// ────────────────────────────────────────────────────────────────
// Rendering: server card
// ────────────────────────────────────────────────────────────────

function buildCard(srv) {
  const card = document.createElement("article");
  card.className = `server-card health-${srv.health}`;
  card.setAttribute("role", "listitem");
  card.setAttribute("tabindex", "0");
  card.setAttribute(
    "aria-label",
    `${srv.server_id} — ${healthLabel(srv.health)}`,
  );

  // Header: id + badge
  const header = document.createElement("div");
  header.className = "server-card__header";

  const idEl = document.createElement("span");
  idEl.className = "server-card__id";
  idEl.textContent = srv.server_id;

  header.appendChild(idEl);
  header.appendChild(createHealthBadge(srv.health));
  card.appendChild(header);

  // Hostname
  const hn = document.createElement("div");
  hn.className = "server-card__hostname";
  hn.textContent = srv.hostname || "—";
  card.appendChild(hn);

  // Last seen
  const ls = document.createElement("div");
  ls.className = "server-card__last-seen";
  const rawTs = srv.last_seen || srv.snapshot_at;
  ls.textContent = rawTs ? `Last seen ${timeAgo(rawTs)}` : "Never seen";
  card.appendChild(ls);

  // Change chips
  const changesRow = document.createElement("div");
  changesRow.className = "server-card__changes";
  const chips = buildChangeChips(srv.change_summary, srv.has_changes);
  chips.forEach((c) => changesRow.appendChild(c));
  card.appendChild(changesRow);

  // Click / keyboard → detail
  const openDetail = () => loadDetail(srv.server_id);
  card.addEventListener("click", openDetail);
  card.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openDetail();
    }
  });

  return card;
}

// ────────────────────────────────────────────────────────────────
// Render: home view
// ────────────────────────────────────────────────────────────────

function renderHome(servers) {
  _servers = servers;

  // Stats
  let healthy = 0,
    stale = 0,
    unknown = 0,
    withChanges = 0;
  for (const s of servers) {
    if (s.health === "healthy") healthy++;
    else if (s.health === "stale") stale++;
    else unknown++;
    if (s.has_changes) withChanges++;
  }
  els.countHealthy.textContent = healthy;
  els.countStale.textContent = stale;
  els.countUnknown.textContent = unknown;
  els.countChanges.textContent = withChanges;

  // Cards
  els.cardGrid.innerHTML = "";
  if (servers.length === 0) {
    els.emptyState.hidden = false;
    els.statsBar.hidden = true;
  } else {
    els.emptyState.hidden = true;
    els.statsBar.hidden = false;
    servers.forEach((srv) => els.cardGrid.appendChild(buildCard(srv)));
  }
}

// ────────────────────────────────────────────────────────────────
// API calls
// ────────────────────────────────────────────────────────────────

async function fetchServers(silent = false) {
  try {
    const res = await fetch("/api/servers", { headers: authHeaders() });
    if (res.status === 401 || res.status === 302 || res.redirected) {
      // Session expired (cookie or token) — back to login.
      handleAuthFailure();
      return;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderHome(data);
    pulseDot();
    if (!silent) showLoading(false);
  } catch (err) {
    if (!silent) showLoading(false);
    showToast("Failed to load server list: " + err.message, true);
  }
}

async function fetchServerDetail(serverId) {
  showLoading(true);
  try {
    const res = await fetch(`/api/server/${encodeURIComponent(serverId)}`, {
      headers: authHeaders(),
    });
    if (res.status === 401) {
      handleAuthFailure();
      return;
    }
    if (!res.ok) {
      throw new Error(`Server not found (HTTP ${res.status})`);
    }
    const data = await res.json();
    renderDetail(data);
    setView("detail");
    fetchApprovalHistory(serverId);
  } catch (err) {
    showToast("Could not load server: " + err.message, true);
  } finally {
    showLoading(false);
  }
}

async function fetchApprovalHistory(serverId) {
  els.approvalHistory.innerHTML = "";
  try {
    const res = await fetch(
      `/api/server/${encodeURIComponent(serverId)}/report-status`,
      { headers: authHeaders() },
    );
    if (res.status === 401) {
      handleAuthFailure();
      return;
    }
    if (!res.ok) return; // Non-fatal: history is a secondary panel.
    const data = await res.json();
    renderApprovalHistory(data.reports || {});
  } catch (err) {
    // Non-fatal: leave the panel empty rather than blocking the detail view.
  }
}

// ────────────────────────────────────────────────────────────────
// Render: detail view
// ────────────────────────────────────────────────────────────────

function renderDetail(data) {
  const sid = data.server_id || "—";

  // Header
  els.detailServerId.textContent = sid;
  els.detailHostname.textContent = data.hostname || "—";

  const health = data.health || "unknown";
  els.detailHealthBadge.className = `health-badge health-${health}`;
  els.detailHealthBadge.textContent = healthLabel(health);

  const rawTs = data.last_seen || data.snapshot_at;
  els.detailLastSeen.textContent = rawTs
    ? `Last seen ${timeAgo(rawTs)}`
    : "Never seen";

  // Full dashboard link
  els.fullDashBtn.href = `/server/${encodeURIComponent(sid)}/dashboard`;

  // Use baseline (cumulative vs. golden) data if available; else incremental.
  const hasBaseline = !!data.baseline_diff;
  const displaySummary = data.baseline_change_summary || data.change_summary;
  const displayHasChanges =
    data.baseline_has_changes !== undefined
      ? data.baseline_has_changes
      : data.has_changes;
  const displayDiff = hasBaseline ? data.baseline_diff : data.diff || {};

  // Change summary chips
  els.changeChips.innerHTML = "";
  buildChangeChips(displaySummary, displayHasChanges).forEach((c) =>
    els.changeChips.appendChild(c),
  );

  // Changed files
  renderChangedFiles(displayDiff, hasBaseline);

  // Metadata
  renderMeta(data);
}

function renderChangedFiles(diff, isBaseline) {
  const list = els.changedFilesList;
  list.innerHTML = "";

  const added = (diff && diff.added) || [];
  const deleted = (diff && diff.deleted) || [];
  const modified = (diff && diff.modified) || [];

  if (added.length === 0 && deleted.length === 0 && modified.length === 0) {
    const msg = document.createElement("div");
    msg.className = "no-changes-msg";
    msg.textContent = "No changes detected in this snapshot.";
    list.appendChild(msg);
    return;
  }

  // Label: let user know if this is baseline or incremental data.
  if (isBaseline) {
    const lbl = document.createElement("div");
    lbl.className = "changed-files-label";
    lbl.textContent = "Changes vs. baseline (first snapshot)";
    list.appendChild(lbl);
  }

  // diff.added/deleted are [{path, type}] objects; diff.modified are [{path, changes, ...}] objects.
  const allChanges = [
    ...added.map((item) => ({
      path: (typeof item === "string" ? item : item.path) || "?",
      badge: "A",
      meta: item && item.type ? item.type : "",
    })),
    ...deleted.map((item) => ({
      path: (typeof item === "string" ? item : item.path) || "?",
      badge: "D",
      meta: item && item.type ? item.type : "",
    })),
    ...modified.map((item) => ({
      path: (typeof item === "string" ? item : item.path) || "?",
      badge: "M",
      meta: item && item.changes ? Object.keys(item.changes).join(", ") : "",
    })),
  ];

  allChanges.forEach((entry) => {
    const badge = entry.badge;
    const filePath = entry.path;

    const item = document.createElement("div");
    item.className = "file-item";
    item.setAttribute("role", "listitem");

    const b = document.createElement("span");
    b.className = `file-item__badge file-item__badge--${badge}`;
    b.textContent = badge;

    const p = document.createElement("span");
    p.className = "file-item__path";
    p.textContent = filePath;

    item.appendChild(b);
    item.appendChild(p);

    if (entry.meta) {
      const m = document.createElement("span");
      m.className = "file-item__meta";
      m.textContent = entry.meta;
      item.appendChild(m);
    }

    list.appendChild(item);
  });
}

function renderMeta(data) {
  const dl = els.snapshotMeta;
  dl.innerHTML = "";

  const fields = [
    ["Server ID", data.server_id],
    ["Hostname", data.hostname],
    ["Snapshot at", data.snapshot_at],
    ["Last seen", data.last_seen],
    [
      "Agent version",
      data.agent_version || data.snapshot?.agent_version || "—",
    ],
    ["Health", healthLabel(data.health || "unknown")],
  ];

  for (const [label, val] of fields) {
    if (!val) continue;
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = val;
    dl.appendChild(dt);
    dl.appendChild(dd);
  }
}

function renderApprovalHistory(reports) {
  const list = els.approvalHistory;
  list.innerHTML = "";

  const entries = Object.keys(reports).map((basename) => ({
    basename,
    ...reports[basename],
  }));
  if (entries.length === 0) {
    const msg = document.createElement("div");
    msg.className = "no-changes-msg";
    msg.textContent = "No reports have been submitted for approval yet.";
    list.appendChild(msg);
    return;
  }

  // Most recently decided/created first.
  entries.sort((a, b) => {
    const at = a.decided_at || a.created_at || "";
    const bt = b.decided_at || b.created_at || "";
    return bt.localeCompare(at);
  });

  entries.forEach((entry) => {
    const item = document.createElement("div");
    item.className = "history-item";
    item.setAttribute("role", "listitem");

    const pill = document.createElement("span");
    pill.className = `history-item__pill history-item__pill--${entry.status || "pending"}`;
    pill.textContent = entry.status || "pending";

    const body = document.createElement("div");
    body.className = "history-item__body";

    const label = document.createElement("div");
    label.className = "history-item__label";
    label.textContent = entry.report_label || entry.basename;
    body.appendChild(label);

    const meta = document.createElement("div");
    meta.className = "history-item__meta";
    const when = entry.decided_at || entry.created_at;
    const whenLabel = entry.decided_at ? "Decided" : "Submitted";
    const changeInfo =
      `${entry.change_count ?? 0} change(s)` +
      (entry.threshold_exceeded ? " (threshold exceeded)" : "");
    meta.textContent = `${whenLabel} ${timeAgo(when)} · ${changeInfo}`;
    body.appendChild(meta);

    if (entry.description) {
      const desc = document.createElement("div");
      desc.className = "history-item__desc";
      desc.textContent = entry.description;
      body.appendChild(desc);
    }

    item.appendChild(pill);
    item.appendChild(body);
    list.appendChild(item);
  });
}

// ────────────────────────────────────────────────────────────────
// Navigation
// ────────────────────────────────────────────────────────────────

function loadDetail(serverId) {
  // Update URL without navigating
  history.pushState(
    { view: "detail", serverId },
    "",
    `/server/${encodeURIComponent(serverId)}`,
  );
  fetchServerDetail(serverId);
}

function goHome() {
  history.pushState({ view: "home" }, "", "/central.html");
  setView("home");
}

// ────────────────────────────────────────────────────────────────
// Auto-refresh + countdown
// ────────────────────────────────────────────────────────────────

function startRefresh() {
  stopRefresh();
  _countdown = REFRESH_INTERVAL_SECS;
  updateCountdown();

  _countdownTimer = setInterval(() => {
    _countdown--;
    if (_countdown <= 0) {
      _countdown = REFRESH_INTERVAL_SECS;
      // Only auto-refresh the home grid (don't disrupt detail view)
      if (_currentView === "home") {
        fetchServers(true);
      }
    }
    updateCountdown();
  }, 1000);
}

function stopRefresh() {
  clearInterval(_countdownTimer);
  clearInterval(_refreshTimer);
}

function updateCountdown() {
  els.refreshCountdown.textContent = `${_countdown}s`;
}

// ────────────────────────────────────────────────────────────────
// Event wiring
// ────────────────────────────────────────────────────────────────

els.backBtn.addEventListener("click", goHome);

if (els.logoutBtn) {
  els.logoutBtn.addEventListener("click", () => {
    // Token-based sessions (iframe) aren't invalidated server-side; just
    // drop the local copy. The /logout navigation still clears the cookie
    // for traditional browser sessions.
    sessionStorage.removeItem(AUTH_TOKEN_KEY);
  });
}

window.addEventListener("popstate", (e) => {
  const state = e.state || {};
  if (state.view === "detail" && state.serverId) {
    fetchServerDetail(state.serverId);
  } else {
    setView("home");
  }
});

// ────────────────────────────────────────────────────────────────
// Boot
// ────────────────────────────────────────────────────────────────

async function init() {
  showLoading(true);
  await fetchServers(false);
  startRefresh();

  // If URL is already a /server/<id> path, load detail
  const m = window.location.pathname.match(/^\/server\/([^/]+)$/);
  if (m) {
    fetchServerDetail(decodeURIComponent(m[1]));
  }
}

init();
