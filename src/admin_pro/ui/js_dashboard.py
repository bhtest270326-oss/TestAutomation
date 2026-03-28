"""
admin_pro/ui/js_dashboard.py
Dashboard section JavaScript for the Admin Pro UI.
"""

JS_DASHBOARD = """
// ---------------------------------------------------------------------------
// Dashboard — KPI cards, pipeline, recent bookings, today's jobs, system status
// ---------------------------------------------------------------------------

async function initDashboard() {
  showDashboardSkeletons();

  const today = new Date().toISOString().slice(0, 10);

  const [statsRes, overviewRes, funnelRes, pendingRes, todayRes, healthRes] =
    await Promise.allSettled([
      apiFetch('/v2/api/bookings/stats'),
      apiFetch('/v2/api/analytics/overview'),
      apiFetch('/v2/api/analytics/funnel'),
      apiFetch('/v2/api/bookings?status=awaiting_owner&per_page=5'),
      apiFetch('/v2/api/bookings?status=confirmed&date_from=' + today + '&date_to=' + today + '&per_page=50'),
      apiFetch('/v2/api/system/health'),
    ]);

  // KPI cards
  try {
    const stats    = statsRes.status === 'fulfilled'    ? statsRes.value    : null;
    const overview = overviewRes.status === 'fulfilled' ? overviewRes.value : null;

    const pendingCount  = stats   ? (stats.awaiting_owner ?? 0) : 0;
    const todayCount    = stats   ? (stats.today           ?? 0) : 0;
    const weekCount     = stats   ? (stats.this_week       ?? 0) : 0;
    const totalConfirmed = stats  ? (stats.confirmed       ?? 0) : 0;

    const convRate = overview ? (overview.conversion_rate ?? null) : null;

    renderKpiCard('kpi-pending', pendingCount, 'Awaiting Approval', 'amber',  '&#9203;', null);
    renderKpiCard('kpi-today',   todayCount,   "Today's Jobs",      'green',  '&#128336;', null);
    renderKpiCard('kpi-week',    weekCount,    'This Week',         'blue',   '&#128197;', null);
    renderKpiCard('kpi-total',   totalConfirmed,'Total Confirmed',  'purple', '&#10003;',
      convRate !== null ? Math.round(convRate) : null);

    // Floating action badge for pending bookings
    updatePendingBadge(pendingCount);
  } catch (err) {
    console.error('Dashboard KPI error:', err);
    showKpiError();
  }

  // Pipeline
  try {
    if (funnelRes.status === 'fulfilled' && funnelRes.value && funnelRes.value.stages) {
      renderPipeline(funnelRes.value.stages);
    } else {
      showPipelineError('Could not load pipeline data');
    }
  } catch (err) {
    console.error('Dashboard pipeline error:', err);
    showPipelineError(err.message);
  }

  // Recent bookings (awaiting owner)
  try {
    if (pendingRes.status === 'fulfilled' && pendingRes.value) {
      renderRecentBookings(pendingRes.value.bookings || []);
    } else {
      renderRecentBookings([]);
    }
  } catch (err) {
    console.error('Dashboard recent bookings error:', err);
    showSectionError('dashboard-recent-bookings', 'Could not load pending bookings');
  }

  // Today's jobs
  try {
    if (todayRes.status === 'fulfilled' && todayRes.value) {
      renderTodayJobs(todayRes.value.bookings || []);
    } else {
      renderTodayJobs([]);
    }
  } catch (err) {
    console.error('Dashboard today jobs error:', err);
    showSectionError('dashboard-today-jobs', "Could not load today's jobs");
  }

  // System status
  try {
    if (healthRes.status === 'fulfilled' && healthRes.value) {
      renderSystemStatus(healthRes.value);
    } else {
      renderSystemStatus(null);
    }
  } catch (err) {
    console.error('Dashboard system status error:', err);
    showSectionError('dashboard-system-status', 'Could not load system status');
  }

  // Auto-refresh every 30 seconds
  setAutoRefresh('dashboard', 30000);
}

// ---------------------------------------------------------------------------
// Loading skeletons
// ---------------------------------------------------------------------------

function showDashboardSkeletons() {
  const kpiIds = ['kpi-pending', 'kpi-today', 'kpi-week', 'kpi-total'];
  const skeletonKpi = `
    <div class="ap-skeleton ap-skeleton-icon"></div>
    <div class="ap-skeleton ap-skeleton-value"></div>
    <div class="ap-skeleton ap-skeleton-label"></div>
  `;
  kpiIds.forEach(function(id) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = skeletonKpi;
  });

  const pipeline = document.getElementById('ap-pipeline');
  if (pipeline) {
    pipeline.innerHTML = '<div class="ap-skeleton ap-skeleton-pipeline"></div>';
  }

  const skeletonRow = `
    <div class="ap-skeleton ap-skeleton-row"></div>
    <div class="ap-skeleton ap-skeleton-row"></div>
    <div class="ap-skeleton ap-skeleton-row"></div>
  `;
  const recentEl = document.getElementById('dashboard-recent-bookings');
  if (recentEl) recentEl.innerHTML = skeletonRow;

  const todayEl = document.getElementById('dashboard-today-jobs');
  if (todayEl) todayEl.innerHTML = skeletonRow;

  const statusEl = document.getElementById('dashboard-system-status');
  if (statusEl) {
    statusEl.innerHTML = '<div class="ap-skeleton ap-skeleton-row"></div>';
  }
}

// ---------------------------------------------------------------------------
// KPI Cards
// ---------------------------------------------------------------------------

function renderKpiCard(id, value, label, color, icon, trend) {
  const el = document.getElementById(id);
  if (!el) return;
  if (trend === undefined) trend = null;
  el.innerHTML = `
    <div class="ap-kpi-icon" style="color:var(--ap-${color})">${icon}</div>
    <div class="ap-kpi-value" style="color:var(--ap-${color})">${value}</div>
    <div class="ap-kpi-label">${label}</div>
    ${trend !== null ? `<div class="ap-kpi-trend ${trend >= 0 ? 'up' : 'down'}">${trend >= 0 ? '&#8593;' : '&#8595;'} ${Math.abs(trend)}%</div>` : ''}
  `;
  const valueEl = el.querySelector('.ap-kpi-value');
  if (valueEl) animateCounter(valueEl, value);
}

function showKpiError() {
  ['kpi-pending', 'kpi-today', 'kpi-week', 'kpi-total'].forEach(function(id) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = '<div class="ap-error-state">&#9888; Error</div>';
  });
}

// ---------------------------------------------------------------------------
// Pipeline Visualization
// ---------------------------------------------------------------------------

function renderPipeline(stages) {
  const container = document.getElementById('ap-pipeline');
  if (!container) return;
  if (!stages || stages.length === 0) {
    container.innerHTML = '<div class="ap-empty-state">No pipeline data available</div>';
    return;
  }

  const icons   = ['&#128231;', '&#128269;', '&#128228;', '&#9989;'];
  const labels  = ['Email In', 'Extracted', 'Sent to Owner', 'Confirmed'];
  const firstCount = stages[0] ? (stages[0].count || 1) : 1;

  let html = '<div class="ap-pipeline-track">';

  stages.forEach(function(stage, idx) {
    const count   = stage.count || 0;
    const pct     = firstCount > 0 ? Math.round((count / firstCount) * 100) : 0;
    const icon    = icons[idx]  || '&#9679;';
    const label   = labels[idx] || stage.label || ('Stage ' + (idx + 1));
    const barW    = Math.max(pct, 4);

    html += `
      <div class="ap-pipeline-node">
        <div class="ap-pipeline-node-icon">${icon}</div>
        <div class="ap-pipeline-node-count">${count.toLocaleString()}</div>
        <div class="ap-pipeline-node-label">${label}</div>
        <div class="ap-pipeline-node-bar">
          <div class="ap-pipeline-node-bar-fill" style="width:${barW}%"></div>
        </div>
        <div class="ap-pipeline-node-pct">${pct}%</div>
      </div>
    `;

    if (idx < stages.length - 1) {
      html += '<div class="ap-pipeline-arrow"><span class="ap-pipeline-arrow-anim">&#10148;</span></div>';
    }
  });

  html += '</div>';
  container.innerHTML = html;
}

function showPipelineError(msg) {
  const container = document.getElementById('ap-pipeline');
  if (container) {
    container.innerHTML = `<div class="ap-error-state">&#9888; ${escHtml(msg || 'Pipeline unavailable')}</div>`;
  }
}

// ---------------------------------------------------------------------------
// Recent Bookings Table
// ---------------------------------------------------------------------------

function renderRecentBookings(bookings) {
  let container = document.getElementById('dashboard-recent-bookings');
  if (!container) {
    const section = document.querySelector('[data-section="dashboard"]') ||
                    document.getElementById('section-dashboard');
    if (section) {
      container = document.createElement('div');
      container.id = 'dashboard-recent-bookings';
      section.appendChild(container);
    } else {
      return;
    }
  }

  if (!bookings || bookings.length === 0) {
    container.innerHTML = '<div class="ap-empty-state">&#10003; No bookings awaiting approval</div>';
    return;
  }

  let rows = '';
  bookings.forEach(function(b) {
    const bd          = b.booking_data || {};
    const name        = escHtml(bd.name || bd.customer_name || b.customer_email || 'Unknown');
    const service     = escHtml(bd.service_type
      ? bd.service_type.replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); })
      : 'Rim Repair');
    const date        = escHtml(b.preferred_date || bd.preferred_date || '—');
    const statusBadge = `<span class="ap-badge ap-badge-amber">Pending</span>`;
    const id          = escHtml(b.id || '');

    rows += `
      <tr>
        <td>${name}</td>
        <td>${service}</td>
        <td>${date}</td>
        <td>${statusBadge}</td>
        <td class="ap-table-actions">
          <button class="ap-btn ap-btn-sm ap-btn-success"
                  onclick="confirmBooking('${id}')">Confirm</button>
          <button class="ap-btn ap-btn-sm ap-btn-danger"
                  onclick="declineBooking('${id}')">Decline</button>
        </td>
      </tr>
    `;
  });

  container.innerHTML = `
    <table class="ap-table ap-table-compact">
      <thead>
        <tr>
          <th>Customer</th>
          <th>Service</th>
          <th>Date</th>
          <th>Status</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

// ---------------------------------------------------------------------------
// Today's Jobs Timeline
// ---------------------------------------------------------------------------

function renderTodayJobs(bookings) {
  const container = document.getElementById('dashboard-today-jobs');
  if (!container) return;

  if (!bookings || bookings.length === 0) {
    container.innerHTML = '<div class="ap-empty-state">No confirmed jobs today</div>';
    return;
  }

  // Sort by preferred_time ascending
  const sorted = bookings.slice().sort(function(a, b) {
    const ta = (a.booking_data || {}).preferred_time || '';
    const tb = (b.booking_data || {}).preferred_time || '';
    return ta.localeCompare(tb);
  });

  let html = '<div class="ap-timeline">';
  sorted.forEach(function(b) {
    const bd     = b.booking_data || {};
    const time   = escHtml(bd.preferred_time || '—');
    const name   = escHtml(bd.name || bd.customer_name || b.customer_email || 'Unknown');
    const suburb = escHtml(bd.suburb || bd.address_suburb || bd.location_suburb || '');
    const service = escHtml(bd.service_type
      ? bd.service_type.replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); })
      : 'Rim Repair');

    html += `
      <div class="ap-timeline-item">
        <div class="ap-timeline-dot"></div>
        <div class="ap-timeline-time">${time}</div>
        <div class="ap-timeline-content">
          <div class="ap-timeline-name">${name}</div>
          <div class="ap-timeline-meta">${service}${suburb ? ' &bull; ' + suburb : ''}</div>
        </div>
      </div>
    `;
  });
  html += '</div>';
  container.innerHTML = html;
}

// ---------------------------------------------------------------------------
// System Status
// ---------------------------------------------------------------------------

function renderSystemStatus(health) {
  const container = document.getElementById('dashboard-system-status');
  if (!container) return;

  const services = [
    { key: 'database',   label: 'Database',   icon: '&#128451;' },
    { key: 'gmail',      label: 'Gmail',      icon: '&#128140;' },
    { key: 'anthropic',  label: 'Anthropic',  icon: '&#129302;' },
    { key: 'twilio',     label: 'Twilio',     icon: '&#128222;' },
  ];

  let html = '<div class="ap-status-row">';
  services.forEach(function(svc) {
    let statusClass = 'ap-status-unknown';
    let statusText  = 'Unknown';

    if (health) {
      const val = health[svc.key];
      if (val === true || val === 'ok' || val === 'healthy') {
        statusClass = 'ap-status-ok';
        statusText  = 'OK';
      } else if (val === false || val === 'error' || val === 'unhealthy') {
        statusClass = 'ap-status-error';
        statusText  = 'Error';
      } else if (val === 'degraded' || val === 'warning') {
        statusClass = 'ap-status-warning';
        statusText  = 'Degraded';
      } else if (val !== null && val !== undefined) {
        statusClass = 'ap-status-ok';
        statusText  = String(val);
      }
    }

    html += `
      <div class="ap-status-item">
        <span class="ap-status-dot ${statusClass}"></span>
        <span class="ap-status-icon">${svc.icon}</span>
        <span class="ap-status-label">${svc.label}</span>
        <span class="ap-status-text ${statusClass}">${statusText}</span>
      </div>
    `;
  });
  html += '</div>';

  if (health && health.last_checked) {
    html += `<div class="ap-status-timestamp">Last checked: ${escHtml(health.last_checked)}</div>`;
  }

  container.innerHTML = html;
}

// ---------------------------------------------------------------------------
// Quick Actions — confirm / decline
// ---------------------------------------------------------------------------

async function confirmBooking(bookingId) {
  try {
    await apiFetch('/v2/api/bookings/' + bookingId + '/confirm', { method: 'POST' });
    showToast('Booking confirmed!', 'success');
    initDashboard();
  } catch (e) {
    showToast(e.message || 'Could not confirm booking', 'error');
  }
}

async function declineBooking(bookingId) {
  if (!confirm('Decline this booking?')) return;
  try {
    await apiFetch('/v2/api/bookings/' + bookingId + '/decline', { method: 'POST' });
    showToast('Booking declined', 'info');
    initDashboard();
  } catch (e) {
    showToast(e.message || 'Could not decline booking', 'error');
  }
}

// ---------------------------------------------------------------------------
// Pending badge
// ---------------------------------------------------------------------------

function updatePendingBadge(count) {
  let badge = document.getElementById('ap-pending-fab');
  if (count > 0) {
    if (!badge) {
      badge = document.createElement('div');
      badge.id = 'ap-pending-fab';
      badge.className = 'ap-fab';
      badge.title = 'Pending bookings';
      badge.setAttribute('onclick', "navigateTo('bookings')");
      document.body.appendChild(badge);
    }
    badge.innerHTML = `
      <span class="ap-fab-icon">&#9203;</span>
      <span class="ap-fab-badge">${count}</span>
    `;
    badge.style.display = 'flex';
  } else {
    if (badge) badge.style.display = 'none';
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function showSectionError(containerId, message) {
  const el = document.getElementById(containerId);
  if (el) {
    el.innerHTML = `<div class="ap-error-state">&#9888; ${escHtml(message || 'An error occurred')}</div>`;
  }
}

function escHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
"""
