JS_CUSTOMERS = """
// ─── Customers Section ────────────────────────────────────────────────────────
// API response formats (no ok/data wrapper):
//   GET /v2/api/customers              → {customers:[...], total:N}
//   GET /v2/api/customers/search?q=... → {results:[...]}
//   GET /v2/api/customers/<b64email>   → {email, name, phone, stats:{...}, bookings:[...], maintenance_due}
//
// HTML IDs:
//   #customers-count, #customer-search, #customers-tbody
//   #customer-detail (side panel), #customer-detail-name
//   #cd-email, #cd-phone, #cd-suburb, #cd-total, #cd-first, #cd-last
//   #customer-bookings-tbody
// ─────────────────────────────────────────────────────────────────────────────

const CUSTOMERS_STATE = { all: [] };

async function initCustomers() {
  await loadCustomers();
}

// ─── Load & Render List ───────────────────────────────────────────────────────

async function loadCustomers() {
  const tbody = document.getElementById('customers-tbody');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="5" class="ap-table-empty"><div class="ap-spinner ap-spinner-sm"></div></td></tr>';
  try {
    const data = await apiFetch('/v2/api/customers');
    CUSTOMERS_STATE.all = data.customers || [];
    renderCustomerTable(CUSTOMERS_STATE.all);
  } catch (e) {
    const tbody2 = document.getElementById('customers-tbody');
    if (tbody2) tbody2.innerHTML = `<tr><td colspan="5" class="ap-table-empty ap-text-danger">${escapeHtml(e.message)}</td></tr>`;
  }
}

function renderCustomerTable(customers) {
  const tbody = document.getElementById('customers-tbody');
  const countEl = document.getElementById('customers-count');
  if (!tbody) return;

  if (countEl) countEl.textContent = `${customers.length} customer${customers.length !== 1 ? 's' : ''}`;

  if (customers.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="ap-table-empty">No customers found</td></tr>';
    return;
  }

  tbody.innerHTML = customers.map(c => {
    // URL-safe base64 of email (compatible with Python urlsafe_b64decode)
    const b64 = btoa(c.email).replace(/\\+/g, '-').replace(/\\//g, '_').replace(/=/g, '');
    return `
      <tr class="ap-table-row-clickable" onclick="openCustomerDetail('${b64}')">
        <td><strong>${escapeHtml(c.name || '—')}</strong></td>
        <td class="ap-text-muted">${escapeHtml(c.email)}</td>
        <td class="ap-text-muted">${escapeHtml(c.phone || '—')}</td>
        <td>${c.total_bookings || 0}</td>
        <td class="ap-text-muted">${c.last_booking ? relativeTime(c.last_booking) : '—'}</td>
      </tr>
    `;
  }).join('');
}

// ─── Search ───────────────────────────────────────────────────────────────────

const searchCustomers = debounce(async function(query) {
  const q = (query || '').trim().toLowerCase();
  if (!q) {
    renderCustomerTable(CUSTOMERS_STATE.all);
    return;
  }
  if (q.length < 2) return;

  // Local filter first for instant results
  const local = CUSTOMERS_STATE.all.filter(c =>
    (c.name || '').toLowerCase().includes(q) ||
    (c.email || '').toLowerCase().includes(q) ||
    (c.phone || '').includes(q)
  );

  if (local.length > 0) {
    renderCustomerTable(local);
    return;
  }

  // Server search fallback
  try {
    const data = await apiFetch(`/v2/api/customers/search?q=${encodeURIComponent(query)}`);
    const results = (data.results || []).map(r => ({
      email: r.email,
      name: r.name,
      phone: r.phone,
      total_bookings: r.booking_count || 0,
      last_booking: null,
    }));
    renderCustomerTable(results);
  } catch (_) {
    renderCustomerTable([]);
  }
}, 300);

// ─── Customer Detail Side Panel ───────────────────────────────────────────────

async function openCustomerDetail(emailB64) {
  const panel = document.getElementById('customer-detail');
  if (!panel) return;

  panel.style.display = 'flex';
  const nameEl = document.getElementById('customer-detail-name');
  if (nameEl) nameEl.textContent = 'Loading…';
  clearCustomerDetailPanel();

  try {
    const data = await apiFetch(`/v2/api/customers/${encodeURIComponent(emailB64)}`);

    if (nameEl) nameEl.textContent = data.name || data.email;

    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val || '—'; };
    set('cd-email', data.email);
    set('cd-phone', data.phone);

    // Extract suburb from most recent booking_data if available
    const suburb = data.bookings?.[0]?.booking_data?.suburb || data.bookings?.[0]?.booking_data?.address || null;
    set('cd-suburb', suburb);

    set('cd-total', data.stats?.total);
    // Derive first/last dates from bookings list
    const dates = (data.bookings || [])
      .map(b => b.booking_data?.preferred_date || b.created_at)
      .filter(Boolean)
      .sort();
    set('cd-first', dates.length ? formatDateShort(dates[0]) : null);
    set('cd-last', dates.length ? formatDateShort(dates[dates.length - 1]) : null);

    // Bookings history table
    const bookTbody = document.getElementById('customer-bookings-tbody');
    if (bookTbody) {
      const bookings = data.bookings || [];
      if (bookings.length === 0) {
        bookTbody.innerHTML = '<tr><td colspan="4" class="ap-table-empty">No bookings</td></tr>';
      } else {
        bookTbody.innerHTML = bookings.map(b => `
          <tr style="cursor:pointer" onclick="openBookingDetail('${b.id}')">
            <td>${b.booking_data?.preferred_date ? formatDateShort(b.booking_data.preferred_date) : '—'}</td>
            <td>${serviceLabel(b.booking_data?.service_type)}</td>
            <td>${b.booking_data?.rim_count || '—'}</td>
            <td>${statusBadge(b.status)}</td>
          </tr>
        `).join('');
      }
    }

    // Maintenance warning
    if (data.maintenance_due) {
      const infoBlock = document.getElementById('customer-info-block');
      if (infoBlock && !document.getElementById('cd-maintenance-warning')) {
        const warn = document.createElement('div');
        warn.id = 'cd-maintenance-warning';
        warn.className = 'ap-card';
        warn.style.cssText = 'border-color:var(--ap-amber);margin-top:10px;padding:10px;font-size:13px';
        warn.textContent = '⚠ Maintenance reminder due';
        infoBlock.after(warn);
      }
    }
  } catch (e) {
    if (nameEl) nameEl.textContent = 'Error loading customer';
    showToast('Failed to load customer: ' + e.message, 'error');
  }
}

function clearCustomerDetailPanel() {
  ['cd-email','cd-phone','cd-suburb','cd-total','cd-first','cd-last'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = '—';
  });
  const tbody = document.getElementById('customer-bookings-tbody');
  if (tbody) tbody.innerHTML = '<tr><td colspan="4" class="ap-table-empty">Loading…</td></tr>';
  const warn = document.getElementById('cd-maintenance-warning');
  if (warn) warn.remove();
}

function closeCustomerDetail() {
  const panel = document.getElementById('customer-detail');
  if (panel) panel.style.display = 'none';
}
// ─── End of Customers Section ─────────────────────────────────────────────────
"""
