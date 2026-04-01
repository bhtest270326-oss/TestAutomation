JS_SYSTEM = """
// ── System Section ────────────────────────────────────────────────────────────

let _metricsRefreshTimer = null;

async function initSystem() {
  injectFlagStyles();
  await Promise.all([
    loadSystemHealth(),
    loadFeatureFlags(),
    loadDbStats(),
    loadBackupStatus(),
    loadPerformanceMetrics(),
    loadUserManagement(),
    loadRolePermissions(),
  ]);
  // Start auto-refresh if checkbox is checked
  const cb = document.getElementById('metrics-autorefresh');
  if (cb && cb.checked) startMetricsAutoRefresh();
}

// ── System Health ─────────────────────────────────────────────────────────────

async function loadSystemHealth() {
  try {
    const h = await apiFetch('/v2/api/system/health');

    function setStatus(id, status, detail) {
      const el = document.getElementById(id);
      if (!el) return;
      const color = (status === 'ok' || status === 'configured') ? 'var(--ap-green)'
                  : (status === 'unconfigured') ? 'var(--ap-amber)' : 'var(--ap-red)';
      el.innerHTML = `<span style="color:${color};font-weight:600">${escapeHtml(status || '—')}</span>${detail ? '<br><small style="color:var(--ap-text-muted)">' + escapeHtml(detail) + '</small>' : ''}`;
    }

    setStatus('health-gmail-status',    h.gmail?.status,     h.gmail?.last_poll ? 'Last poll: ' + relativeTime(h.gmail.last_poll) : null);
    setStatus('health-calendar-status', h.anthropic?.status, null);
    setStatus('health-twilio-status',   h.twilio?.status,    h.uptime_info?.pubsub_mode ? 'Pub/Sub mode' : 'Polling mode');
    setStatus('health-db-status',       h.db?.status,        h.db ? (h.db.size_mb?.toFixed(2) + ' MB · ' + (h.db.bookings_count || 0) + ' bookings') : null);
  } catch (err) {
    console.error('loadSystemHealth error:', err);
  }
}

async function manualGmailPoll() {
  try {
    showToast('Polling Gmail inbox…', 'info');
    await apiFetch('/v2/api/gmail/poll', { method: 'POST' });
    showToast('Gmail poll complete', 'success');
    loadSystemHealth();
  } catch (err) {
    showToast('Gmail poll failed: ' + err.message, 'error');
  }
}

// ── Feature Flags ─────────────────────────────────────────────────────────────

async function loadFeatureFlags() {
  const container = document.getElementById('system-flags');
  if (!container) return;
  try {
    const data = await apiFetch('/v2/api/system/flags');
    const flags = data.flags || {};

    container.innerHTML = `
      <h3 class="ap-card-title ap-mb-16">Feature Flags</h3>
      <div class="ap-flags-grid">
        ${Object.entries(flags).map(([key, flag]) => `
          <div class="ap-flag-card ${flag.enabled ? 'enabled' : 'disabled'}" id="flag-card-${key}">
            <div class="ap-flag-info">
              <div class="ap-flag-label-row">
                <span class="ap-flag-label">${escapeHtml(flag.label)}</span>
                <span class="ap-flag-info-icon" tabindex="0" aria-label="${escapeHtml(flag.description)}">i<span class="ap-flag-tooltip">${escapeHtml(flag.description)}</span></span>
              </div>
            </div>
            <label class="ap-toggle" title="${flag.enabled ? 'Enabled — click to disable' : 'Disabled — click to enable'}">
              <input type="checkbox" ${flag.enabled ? 'checked' : ''} onchange="toggleFlag('${key}', this.checked)">
              <span class="ap-toggle-slider"></span>
            </label>
          </div>
        `).join('')}
      </div>
    `;
  } catch (err) {
    console.error('loadFeatureFlags error:', err);
    if (container) container.innerHTML = '<div class="ap-text-muted">Failed to load feature flags.</div>';
  }
}

async function toggleFlag(key, enabled) {
  try {
    const data = await apiFetch(`/v2/api/system/flags/${key}`, {
      method: 'POST',
      body: JSON.stringify({ enabled })
    });
    const card = document.getElementById(`flag-card-${key}`);
    if (card) {
      card.classList.toggle('enabled', enabled);
      card.classList.toggle('disabled', !enabled);
    }
    showToast(`${key.replace('flag_','').replace(/_/g,' ')} ${enabled ? 'enabled' : 'disabled'}`, 'success');
  } catch(e) {
    showToast('Failed to update flag: ' + e.message, 'error');
    loadFeatureFlags(); // Reset to server state
  }
}

// ── Database Stats ────────────────────────────────────────────────────────────

async function loadDbStats() {
  try {
    const stats = await apiFetch('/v2/api/system/db-stats');
    const tables = stats?.tables || [];

    // Update individual stat spans in the existing HTML
    const bookings = tables.find(t => t.name === 'bookings');
    const customers = tables.find(t => t.name === 'customers');
    const dlq       = tables.find(t => t.name === 'dlq' || t.name === 'dead_letter_queue');
    const waitlist  = tables.find(t => t.name === 'waitlist');

    function setVal(id, val) { const el = document.getElementById(id); if (el) el.textContent = val; }
    setVal('dbstat-bookings', bookings ? bookings.count.toLocaleString() : '—');
    setVal('dbstat-customers', customers ? customers.count.toLocaleString() : '—');
    setVal('dbstat-dlq',      dlq       ? dlq.count.toLocaleString()      : '—');
    setVal('dbstat-waitlist', waitlist   ? waitlist.count.toLocaleString() : '—');
    setVal('dbstat-size',     '—');   // not returned separately
    setVal('dbstat-vacuum',   '—');

    // Also inject a compact table below for all tables
    const grid = document.getElementById('db-stats-grid');
    if (grid && tables.length > 0) {
      const extra = document.getElementById('db-stats-table');
      if (!extra) {
        const div = document.createElement('div');
        div.id = 'db-stats-table';
        div.style.cssText = 'margin-top:12px;border-top:1px solid var(--ap-border);padding-top:12px';
        div.innerHTML = '<div class="ap-text-muted" style="font-size:12px;margin-bottom:6px">All tables</div>' +
          tables.map(t => `<div class="ap-stat-row"><span class="ap-stat-label">${escapeHtml(t.name)}</span><span class="ap-stat-val">${t.count.toLocaleString()}</span></div>`).join('') +
          `<div class="ap-stat-row" style="font-weight:600;border-top:1px solid var(--ap-border);margin-top:4px;padding-top:4px"><span class="ap-stat-label">Total rows</span><span class="ap-stat-val">${(stats.total_rows||0).toLocaleString()}</span></div>`;
        grid.parentElement.appendChild(div);
      }
    }
  } catch (err) {
    console.error('loadDbStats error:', err);
  }
}

// ── Cancel Day (uses IDs from static HTML: cancel-day-date, cancel-day-reason) ──

function cancelDayPrompt() { submitSystemCancelDay(); }

async function submitSystemCancelDay() {
  // Support both the static HTML IDs and the dynamically-injected IDs
  const dateEl   = document.getElementById('cancel-day-date')   || document.getElementById('system-cancel-date');
  const reasonEl = document.getElementById('cancel-day-reason') || document.getElementById('system-cancel-reason');
  const date   = dateEl   ? dateEl.value.trim()   : '';
  const reason = reasonEl ? reasonEl.value.trim() : '';
  if (!date)   { showToast('Please select a date', 'warning');    return; }
  if (!reason) { showToast('Please provide a reason', 'warning'); return; }
  if (!confirm(`Cancel ALL bookings on ${formatDate(date)}? This will notify all customers.`)) return;
  try {
    const data = await apiFetch('/v2/api/system/cancel-day', {method: 'POST', body: JSON.stringify({date, reason})});
    showToast(`${data.cancelled || 0} booking(s) cancelled and customers notified`, 'success');
    if (dateEl)   dateEl.value   = '';
    if (reasonEl) reasonEl.value = '';
  } catch (err) {
    showToast('Failed to cancel day: ' + err.message, 'error');
  }
}

// ── Database Actions ─────────────────────────────────────────────────────────

async function vacuumDb() {
  if (!confirm('Run VACUUM on the database?')) return;
  try {
    await apiFetch('/api/system/vacuum', {method:'POST'});
    showToast('Database vacuumed successfully.', 'success');
  } catch(e) { showToast('Vacuum failed: ' + e.message, 'error'); }
}

async function exportDb() {
  if (!confirm('Trigger a database backup to Google Drive now?')) return;
  try {
    showToast('Starting backup...', 'info', 3000);
    const result = await apiFetch('/api/system/backup-now', {method: 'POST'});
    if (result.ok) {
      const sizeMb = (result.size_bytes / 1048576).toFixed(2);
      showToast('Backup complete (' + sizeMb + ' MB). ' + result.backups_retained + ' backups retained.', 'success', 6000);
    } else {
      showToast('Backup failed: ' + (result.error || 'Unknown error'), 'error');
    }
  } catch(e) {
    showToast('Backup failed: ' + e.message, 'error');
  }
}

// ── Backup Status ───────────────────────────────────────────────────────────

async function loadBackupStatus() {
  try {
    const data = await apiFetch('/api/system/backup-status');
    const el = document.getElementById('backup-status');
    if (!el) return;
    if (data.last_drive_backup_date) {
      const sizeMb = data.last_drive_backup_size ? (data.last_drive_backup_size / 1048576).toFixed(2) + ' MB' : '—';
      el.innerHTML = '<span class="ap-text-dim">Last backup:</span> ' +
        escapeHtml(data.last_drive_backup_date) + ' at ' + escapeHtml(data.last_drive_backup_time || '—') +
        ' <span class="ap-text-dim">(' + sizeMb + ')</span>';
    } else {
      el.innerHTML = '<span class="ap-text-muted">No backups yet</span>';
    }
  } catch(e) {
    const el = document.getElementById('backup-status');
    if (el) el.innerHTML = '<span class="ap-text-muted">Could not load backup status</span>';
  }
}

// ── App State Viewer ─────────────────────────────────────────────────────────

async function loadAppState() {
  try {
    const data = await apiFetch('/api/system/app-state');
    const raw = document.getElementById('app-state-raw');
    const formatted = document.getElementById('app-state-formatted');
    if (raw) raw.textContent = JSON.stringify(data, null, 2);
    if (formatted) formatted.innerHTML = '<pre style="white-space:pre-wrap;word-break:break-word">' + escapeHtml(JSON.stringify(data, null, 2)) + '</pre>';
  } catch(e) {
    showToast('Failed to load app state: ' + e.message, 'error');
  }
}

function toggleAppStateRaw() {
  const raw = document.getElementById('app-state-raw');
  const formatted = document.getElementById('app-state-formatted');
  if (!raw || !formatted) return;
  if (raw.style.display === 'none') {
    raw.style.display = 'block';
    formatted.style.display = 'none';
  } else {
    raw.style.display = 'none';
    formatted.style.display = 'block';
  }
}

// ── Performance Metrics ──────────────────────────────────────────────────────

function formatUptime(seconds) {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return d + 'd ' + h + 'h ' + m + 'm';
  if (h > 0) return h + 'h ' + m + 'm';
  return m + 'm';
}

async function loadPerformanceMetrics() {
  try {
    const data = await apiFetch('/v2/api/system/metrics');

    // Uptime
    const uptimeEl = document.getElementById('metric-uptime-val');
    if (uptimeEl) uptimeEl.innerHTML = '<span style="color:var(--ap-green);font-weight:600">' + formatUptime(data.uptime_seconds || 0) + '</span>';

    // Memory
    const memEl = document.getElementById('metric-memory-val');
    if (memEl) {
      const mem = data.system_info?.memory_mb;
      const color = mem && mem > 512 ? 'var(--ap-amber)' : 'var(--ap-green)';
      memEl.innerHTML = mem != null ? '<span style="color:' + color + ';font-weight:600">' + mem + ' MB</span>' : '<span class="ap-text-muted">N/A</span>';
    }

    // Conversion rates
    const c7d = data.conversion?.['7d'];
    const c30d = data.conversion?.['30d'];
    const c7El = document.getElementById('metric-conversion-7d-val');
    const c30El = document.getElementById('metric-conversion-30d-val');
    if (c7El && c7d) {
      c7El.innerHTML = '<span style="font-weight:600;color:var(--ap-primary)">' + c7d.rate + '%</span>' +
        '<br><small class="ap-text-muted">' + c7d.confirmed + '/' + c7d.total + ' bookings</small>';
    }
    if (c30El && c30d) {
      c30El.innerHTML = '<span style="font-weight:600;color:var(--ap-primary)">' + c30d.rate + '%</span>' +
        '<br><small class="ap-text-muted">' + c30d.confirmed + '/' + c30d.total + ' bookings</small>';
    }

    // Queue depth
    const queuesEl = document.getElementById('metrics-queues');
    if (queuesEl && data.queues) {
      const dlq = data.queues.dlq || 0;
      const retry = data.queues.retry_pending || 0;
      const dlqColor = dlq > 0 ? 'var(--ap-red)' : 'var(--ap-green)';
      const retryColor = retry > 0 ? 'var(--ap-amber)' : 'var(--ap-green)';
      queuesEl.innerHTML =
        '<div class="ap-stat-row"><span class="ap-stat-label">Dead Letter Queue</span><span class="ap-stat-val" style="color:' + dlqColor + '">' + dlq + '</span></div>' +
        '<div class="ap-stat-row"><span class="ap-stat-label">Retry Pending</span><span class="ap-stat-val" style="color:' + retryColor + '">' + retry + '</span></div>';
    }

    // System info
    const sysEl = document.getElementById('metrics-sysinfo');
    if (sysEl && data.system_info) {
      const si = data.system_info;
      sysEl.innerHTML =
        '<div class="ap-stat-row"><span class="ap-stat-label">Python</span><span class="ap-stat-val">' + escapeHtml(si.python_version || '--') + '</span></div>' +
        '<div class="ap-stat-row"><span class="ap-stat-label">DB Size</span><span class="ap-stat-val">' + (si.db_size_mb || 0) + ' MB</span></div>';
    }

    // Response times table
    const rtEl = document.getElementById('metrics-response-times');
    if (rtEl && data.response_times) {
      const entries = Object.entries(data.response_times)
        .filter(([,v]) => v.count_1h > 0 || v.count_24h > 0)
        .sort((a, b) => (b[1].count_24h || 0) - (a[1].count_24h || 0))
        .slice(0, 15);

      if (entries.length === 0) {
        rtEl.innerHTML = '<span class="ap-text-muted">No request data yet</span>';
      } else {
        let html = '<table style="width:100%;font-size:13px;border-collapse:collapse">' +
          '<thead><tr style="border-bottom:1px solid var(--ap-border);text-align:left">' +
          '<th style="padding:6px 8px">Endpoint</th>' +
          '<th style="padding:6px 8px;text-align:right">Avg 1h</th>' +
          '<th style="padding:6px 8px;text-align:right">P95 1h</th>' +
          '<th style="padding:6px 8px;text-align:right">Avg 24h</th>' +
          '<th style="padding:6px 8px;text-align:right">Reqs 24h</th>' +
          '</tr></thead><tbody>';
        for (const [ep, v] of entries) {
          const avg1h = v.avg_1h != null ? v.avg_1h + 'ms' : '--';
          const p95 = v.p95_1h != null ? v.p95_1h + 'ms' : '--';
          const avg24h = v.avg_24h != null ? v.avg_24h + 'ms' : '--';
          const avgColor = v.avg_1h && v.avg_1h > 1000 ? 'color:var(--ap-red)' : v.avg_1h && v.avg_1h > 500 ? 'color:var(--ap-amber)' : '';
          html += '<tr style="border-bottom:1px solid var(--ap-border)">' +
            '<td style="padding:6px 8px;font-family:monospace;font-size:12px">' + escapeHtml(ep) + '</td>' +
            '<td style="padding:6px 8px;text-align:right;' + avgColor + '">' + avg1h + '</td>' +
            '<td style="padding:6px 8px;text-align:right">' + p95 + '</td>' +
            '<td style="padding:6px 8px;text-align:right">' + avg24h + '</td>' +
            '<td style="padding:6px 8px;text-align:right">' + v.count_24h + '</td>' +
            '</tr>';
        }
        html += '</tbody></table>';
        rtEl.innerHTML = html;
      }
    }
  } catch (err) {
    console.error('loadPerformanceMetrics error:', err);
  }
}

function startMetricsAutoRefresh() {
  stopMetricsAutoRefresh();
  _metricsRefreshTimer = setInterval(() => loadPerformanceMetrics(), 30000);
}

function stopMetricsAutoRefresh() {
  if (_metricsRefreshTimer) { clearInterval(_metricsRefreshTimer); _metricsRefreshTimer = null; }
}

function toggleMetricsAutoRefresh(enabled) {
  if (enabled) startMetricsAutoRefresh();
  else stopMetricsAutoRefresh();
}

// ── Flag & Toggle Styles ──────────────────────────────────────────────────────

function injectFlagStyles() {
  if (document.getElementById('ap-flag-styles')) return;
  const style = document.createElement('style');
  style.id = 'ap-flag-styles';
  style.textContent = `
    .ap-flags-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; }
    .ap-flag-card { display:flex; justify-content:space-between; align-items:center; padding:16px; background:var(--ap-card); border:1px solid var(--ap-border); border-radius:var(--ap-radius-sm); transition:.2s; }
    .ap-flag-card.enabled { border-color: rgba(34,197,94,0.3); }
    .ap-flag-card.disabled { opacity:.7; }
    .ap-flag-label-row { display:flex; align-items:center; gap:6px; }
    .ap-flag-label { font-weight:600; font-size:14px; }
    .ap-flag-info-icon { position:relative; display:inline-flex; align-items:center; justify-content:center; width:15px; height:15px; background:var(--ap-text-muted); color:#0f0f0f; border-radius:50%; font-size:10px; font-weight:700; font-style:italic; font-family:serif; cursor:pointer; flex-shrink:0; user-select:none; transition:background .15s; }
    .ap-flag-info-icon:hover { background:var(--ap-primary); }
    .ap-flag-tooltip { visibility:hidden; opacity:0; position:absolute; bottom:calc(100% + 8px); left:50%; transform:translateX(-50%); background:#1e1e1e; color:var(--ap-text); font-size:12px; font-weight:400; line-height:1.5; padding:8px 12px; border-radius:8px; border:1px solid var(--ap-border-light); box-shadow:0 4px 16px rgba(0,0,0,0.5); white-space:normal; width:240px; text-align:left; pointer-events:none; transition:opacity .15s, visibility .15s; z-index:999; }
    .ap-flag-tooltip::after { content:''; position:absolute; top:100%; left:50%; transform:translateX(-50%); border:6px solid transparent; border-top-color:#1e1e1e; }
    .ap-flag-info-icon:hover .ap-flag-tooltip,
    .ap-flag-info-icon:focus .ap-flag-tooltip { visibility:visible; opacity:1; }
    .ap-toggle { position:relative; width:44px; height:24px; flex-shrink:0; margin-left:12px; }
    .ap-toggle input { opacity:0; width:0; height:0; }
    .ap-toggle-slider { position:absolute; inset:0; background:#334155; border-radius:24px; cursor:pointer; transition:.2s; }
    .ap-toggle-slider:before { content:''; position:absolute; height:18px; width:18px; left:3px; top:3px; background:white; border-radius:50%; transition:.2s; }
    .ap-toggle input:checked + .ap-toggle-slider { background:var(--ap-green); }
    .ap-toggle input:checked + .ap-toggle-slider:before { transform:translateX(20px); }
  `;
  document.head.appendChild(style);
}

// ── User Management (owner only) ─────────────────────────────────────────────

async function loadUserManagement() {
  var container = document.getElementById('system-user-mgmt');
  if (!container) return;
  var user = window.AP_USER;
  if (!user || user.role !== 'owner') {
    container.style.display = 'none';
    return;
  }
  container.style.display = 'block';

  try {
    var data = await apiFetch('/api/users');
    var users = (data.data && data.data.users) || [];
    var rows = users.map(function(u) {
      var roleCls = 'ap-role-badge ap-role-badge--' + escapeHtml(u.role);
      var statusCls = u.is_active ? 'ap-badge ap-badge--green' : 'ap-badge ap-badge--grey';
      var statusLabel = u.is_active ? 'Active' : 'Inactive';
      var rowCls = u.is_active ? '' : ' class="ap-user-inactive"';
      return '<tr' + rowCls + '>' +
        '<td>' + escapeHtml(u.username) + '</td>' +
        '<td>' + escapeHtml(u.display_name || '') + '</td>' +
        '<td><span class="' + roleCls + '">' + escapeHtml(u.role) + '</span></td>' +
        '<td><span class="' + statusCls + '">' + statusLabel + '</span></td>' +
        '<td>' + (u.last_login_at ? relativeTime(u.last_login_at) : 'Never') + '</td>' +
        '<td>' +
          '<button class="ap-btn ap-btn-ghost ap-btn-xs" onclick="showEditUserModal(' + u.id + ')">Edit</button> ' +
          (u.is_active
            ? '<button class="ap-btn ap-btn-ghost ap-btn-xs" style="color:var(--ap-red)" data-uid="' + u.id + '" data-uname="' + escapeHtml(u.username) + '" onclick="deactivateUser(+this.dataset.uid, this.dataset.uname)">Deactivate</button>'
            : '<button class="ap-btn ap-btn-ghost ap-btn-xs" style="color:var(--ap-green)" onclick="activateUser(' + u.id + ')">Activate</button>') +
        '</td>' +
      '</tr>';
    }).join('');

    container.innerHTML =
      '<h3 class="ap-card-title ap-mb-16">User Management</h3>' +
      '<div style="margin-bottom:12px">' +
        '<button class="ap-btn ap-btn-primary ap-btn-sm" onclick="showAddUserModal()">Add User</button>' +
      '</div>' +
      '<div style="overflow-x:auto">' +
        '<table class="ap-users-table">' +
          '<thead><tr>' +
            '<th>Username</th><th>Display Name</th><th>Role</th><th>Status</th><th>Last Login</th><th>Actions</th>' +
          '</tr></thead>' +
          '<tbody>' + rows + '</tbody>' +
        '</table>' +
      '</div>';
  } catch (err) {
    container.innerHTML = '<h3 class="ap-card-title ap-mb-16">User Management</h3>' +
      '<p style="color:var(--ap-red)">Failed to load users: ' + escapeHtml(err.message) + '</p>';
  }
}

function showAddUserModal() {
  showModal(
    'Add User',
    '<div class="ap-form-group">' +
      '<label class="ap-label" for="um-username">Username</label>' +
      '<input class="ap-input" id="um-username" type="text" placeholder="Username" autocomplete="off">' +
    '</div>' +
    '<div class="ap-form-group ap-mt-16">' +
      '<label class="ap-label" for="um-display-name">Display Name</label>' +
      '<input class="ap-input" id="um-display-name" type="text" placeholder="Display name" autocomplete="off">' +
    '</div>' +
    '<div class="ap-form-group ap-mt-16">' +
      '<label class="ap-label" for="um-password">Password</label>' +
      '<input class="ap-input" id="um-password" type="password" placeholder="Min 8 characters" autocomplete="new-password">' +
    '</div>' +
    '<div class="ap-form-group ap-mt-16">' +
      '<label class="ap-label" for="um-role">Role</label>' +
      '<select class="ap-input" id="um-role">' +
        '<option value="owner">Owner</option>' +
        '<option value="user" selected>User</option>' +
        '<option value="technician">Technician</option>' +
      '</select>' +
    '</div>',
    '<button class="ap-btn ap-btn-primary" onclick="submitAddUser()">Create User</button>' +
    '<button class="ap-btn ap-btn-ghost" onclick="closeModal()">Cancel</button>'
  );
}

async function submitAddUser() {
  var username = (document.getElementById('um-username') || {}).value || '';
  var displayName = (document.getElementById('um-display-name') || {}).value || '';
  var password = (document.getElementById('um-password') || {}).value || '';
  var role = (document.getElementById('um-role') || {}).value || 'user';

  if (!username.trim()) {
    showToast('Username is required.', 'warning');
    return;
  }
  if (password.length < 8) {
    showToast('Password must be at least 8 characters.', 'warning');
    return;
  }

  try {
    await apiFetch('/api/users', {
      method: 'POST',
      body: JSON.stringify({
        username: username.trim(),
        password: password,
        display_name: displayName.trim(),
        role: role
      })
    });
    closeModal();
    showToast('User created successfully.', 'success');
    loadUserManagement();
  } catch (err) {
    showToast('Failed to create user: ' + (err.message || 'Unknown error'), 'error');
  }
}

async function showEditUserModal(userId) {
  try {
    var data = await apiFetch('/api/users');
    var users = (data.data && data.data.users) || [];
    var u = users.find(function(x) { return x.id === userId; });
    if (!u) { showToast('User not found.', 'error'); return; }

    showModal(
      'Edit User — ' + escapeHtml(u.username),
      '<div class="ap-form-group">' +
        '<label class="ap-label">Username</label>' +
        '<input class="ap-input" type="text" value="' + escapeHtml(u.username) + '" disabled readonly>' +
      '</div>' +
      '<div class="ap-form-group ap-mt-16">' +
        '<label class="ap-label" for="um-edit-display-name">Display Name</label>' +
        '<input class="ap-input" id="um-edit-display-name" type="text" value="' + escapeHtml(u.display_name || '') + '">' +
      '</div>' +
      '<div class="ap-form-group ap-mt-16">' +
        '<label class="ap-label" for="um-edit-password">New Password <small style="color:var(--ap-text-muted)">(leave blank to keep current)</small></label>' +
        '<input class="ap-input" id="um-edit-password" type="password" placeholder="Optional" autocomplete="new-password">' +
      '</div>' +
      '<div class="ap-form-group ap-mt-16">' +
        '<label class="ap-label" for="um-edit-role">Role</label>' +
        '<select class="ap-input" id="um-edit-role">' +
          '<option value="owner"' + (u.role === 'owner' ? ' selected' : '') + '>Owner</option>' +
          '<option value="user"' + (u.role === 'user' ? ' selected' : '') + '>User</option>' +
          '<option value="technician"' + (u.role === 'technician' ? ' selected' : '') + '>Technician</option>' +
        '</select>' +
      '</div>',
      '<button class="ap-btn ap-btn-primary" onclick="submitEditUser(' + userId + ')">Save Changes</button>' +
      '<button class="ap-btn ap-btn-ghost" onclick="closeModal()">Cancel</button>'
    );
  } catch (err) {
    showToast('Failed to load user: ' + (err.message || 'Unknown error'), 'error');
  }
}

async function submitEditUser(userId) {
  var displayName = (document.getElementById('um-edit-display-name') || {}).value || '';
  var password = (document.getElementById('um-edit-password') || {}).value || '';
  var role = (document.getElementById('um-edit-role') || {}).value || 'user';

  var body = { display_name: displayName.trim(), role: role };
  if (password) {
    if (password.length < 8) {
      showToast('Password must be at least 8 characters.', 'warning');
      return;
    }
    body.password = password;
  }

  try {
    await apiFetch('/api/users/' + userId, {
      method: 'PUT',
      body: JSON.stringify(body)
    });
    closeModal();
    showToast('User updated successfully.', 'success');
    loadUserManagement();
  } catch (err) {
    showToast('Failed to update user: ' + (err.message || 'Unknown error'), 'error');
  }
}

async function deactivateUser(userId, username) {
  if (!confirm('Deactivate user "' + username + '"? They will no longer be able to log in.')) return;
  try {
    await apiFetch('/api/users/' + userId, { method: 'DELETE' });
    showToast('User deactivated.', 'success');
    loadUserManagement();
  } catch (err) {
    showToast('Failed to deactivate: ' + (err.message || 'Unknown error'), 'error');
  }
}

async function activateUser(userId) {
  try {
    await apiFetch('/api/users/' + userId, {
      method: 'PUT',
      body: JSON.stringify({ is_active: true })
    });
    showToast('User activated.', 'success');
    loadUserManagement();
  } catch (err) {
    showToast('Failed to activate: ' + (err.message || 'Unknown error'), 'error');
  }
}

// ── Role Permission Editor ───────────────────────────────────────────────────

async function loadRolePermissions() {
  var container = document.getElementById('system-role-perms');
  if (!container) return;
  var user = window.AP_USER;
  if (!user || user.role !== 'owner') {
    container.style.display = 'none';
    return;
  }
  container.style.display = 'block';

  try {
    var data = await apiFetch('/api/roles');
    var roles = (data.data && data.data.roles) || [];
    var allTabs = (data.data && data.data.all_tabs) || [];

    // Build header row
    var headerCells = '<th>Tab</th>';
    roles.forEach(function(r) {
      headerCells += '<th colspan="2" style="text-align:center">' + escapeHtml(r.display_name || r.role) + '</th>';
    });

    // Build sub-header
    var subHeader = '<th></th>';
    roles.forEach(function() {
      subHeader += '<th style="text-align:center;font-size:11px">View</th><th style="text-align:center;font-size:11px">Edit</th>';
    });

    // Build body rows
    var bodyRows = '';
    allTabs.forEach(function(tab) {
      bodyRows += '<tr><td>' + escapeHtml(tab.label) + '</td>';
      roles.forEach(function(r) {
        var isOwner = (r.role === 'owner');
        var perms = (r.permissions && r.permissions[tab.id]) || {};
        var viewChecked = isOwner || perms.can_view !== false;
        var editChecked = isOwner || perms.can_edit === true;
        bodyRows +=
          '<td style="text-align:center"><input type="checkbox" data-role="' + r.role + '" data-tab="' + tab.id + '" data-perm="can_view"' +
            (viewChecked ? ' checked' : '') + (isOwner ? ' disabled' : '') + '></td>' +
          '<td style="text-align:center"><input type="checkbox" data-role="' + r.role + '" data-tab="' + tab.id + '" data-perm="can_edit"' +
            (editChecked ? ' checked' : '') + (isOwner ? ' disabled' : '') + '></td>';
      });
      bodyRows += '</tr>';
    });

    // Build save buttons per editable role
    var saveButtons = '';
    roles.forEach(function(r) {
      if (r.role !== 'owner') {
        saveButtons += '<button class="ap-btn ap-btn-primary ap-btn-sm" style="margin-right:8px" onclick="saveRolePermissions(\'' + r.role + '\')">Save ' + escapeHtml(r.display_name || r.role) + '</button>';
      }
    });

    container.innerHTML =
      '<h3 class="ap-card-title ap-mb-16">Role Permissions</h3>' +
      '<div style="overflow-x:auto">' +
        '<table class="ap-perm-matrix">' +
          '<thead><tr>' + headerCells + '</tr><tr>' + subHeader + '</tr></thead>' +
          '<tbody>' + bodyRows + '</tbody>' +
        '</table>' +
      '</div>' +
      '<div style="margin-top:12px">' + saveButtons + '</div>';
  } catch (err) {
    container.innerHTML = '<h3 class="ap-card-title ap-mb-16">Role Permissions</h3>' +
      '<p style="color:var(--ap-red)">Failed to load roles: ' + escapeHtml(err.message) + '</p>';
  }
}

async function saveRolePermissions(role) {
  var checkboxes = document.querySelectorAll('.ap-perm-matrix input[type="checkbox"][data-role="' + role + '"]');
  var permissions = {};

  checkboxes.forEach(function(cb) {
    var tab = cb.dataset.tab;
    var perm = cb.dataset.perm;
    if (!permissions[tab]) permissions[tab] = {};
    permissions[tab][perm] = cb.checked;
  });

  try {
    await apiFetch('/api/roles/' + role + '/permissions', {
      method: 'PUT',
      body: JSON.stringify({ permissions: permissions })
    });
    showToast('Permissions saved for ' + role + '.', 'success');
  } catch (err) {
    showToast('Failed to save permissions: ' + (err.message || 'Unknown error'), 'error');
  }
}
"""
