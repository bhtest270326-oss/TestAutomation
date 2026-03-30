"""
admin_pro/ui/js_quotes.py
Quotes section JavaScript for the Admin Pro dashboard.
"""

JS_QUOTES = """
// ============================================================
// Admin Pro — Quotes Section
// ============================================================

async function initQuotes() {
  await loadQuotesList();
}

async function loadQuotesList() {
  const tbody = document.getElementById('quotes-tbody');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="7" class="ap-table-empty">Loading quotes...</td></tr>';

  try {
    const res = await apiFetch('/api/quotes/list');
    const quotes = (res && res.data) || [];

    if (quotes.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" class="ap-table-empty">No quotes found.</td></tr>';
      return;
    }

    tbody.innerHTML = quotes.map(renderQuoteRow).join('');
  } catch (err) {
    tbody.innerHTML = '<tr><td colspan="7" class="ap-table-empty">Error loading quotes: ' + escapeHtml(err.message) + '</td></tr>';
  }
}

function renderQuoteRow(q) {
  var id = escapeHtml(q.id || '-');
  var bookingId = q.booking_id ? escapeHtml(q.booking_id) : '-';
  var service = serviceLabel(q.service_key || '');
  var priceRange = (q.estimate_low != null && q.estimate_high != null)
    ? ('$' + Number(q.estimate_low).toFixed(0) + ' - $' + Number(q.estimate_high).toFixed(0))
    : '-';
  var confidence = q.confidence != null ? (Number(q.confidence) * 100).toFixed(0) + '%' : '-';
  var date = q.created_at ? formatDateTime(q.created_at) : '-';

  return '<tr>' +
    '<td>' + id + '</td>' +
    '<td>' + bookingId + '</td>' +
    '<td>' + escapeHtml(service) + '</td>' +
    '<td>' + priceRange + '</td>' +
    '<td>' + confidence + '</td>' +
    '<td>' + date + '</td>' +
    '<td><button class="ap-btn ap-btn-ghost ap-btn-sm" onclick="viewQuoteDetail(\\'' + escapeHtml(String(id)) + '\\')">View</button></td>' +
    '</tr>';
}

function viewQuoteDetail(quoteId) {
  showModal(
    'Quote #' + escapeHtml(quoteId),
    '<div class="ap-table-empty" id="quote-detail-body">Loading...</div>',
    '<button class="ap-btn ap-btn-ghost" onclick="closeModal()">Close</button>'
  );

  // Try to find the quote in the table data or fetch it
  apiFetch('/api/quotes/list').then(function(res) {
    var quotes = (res && res.data) || [];
    var q = quotes.find(function(item) {
      return String(item.id) === String(quoteId) || String(item.quote_id) === String(quoteId);
    });

    var body = document.getElementById('quote-detail-body');
    if (!body) return;

    if (!q) {
      body.innerHTML = 'Quote not found.';
      return;
    }

    var priceRange = (q.estimate_low != null && q.estimate_high != null)
      ? ('$' + Number(q.estimate_low).toFixed(0) + ' - $' + Number(q.estimate_high).toFixed(0))
      : '-';
    var confidence = q.confidence != null ? (Number(q.confidence) * 100).toFixed(0) + '%' : '-';

    var html = '<table class="ap-table" style="margin:0"><tbody>';
    html += '<tr><td><strong>Service Type</strong></td><td>' + escapeHtml(serviceLabel(q.service_key || '')) + '</td></tr>';
    html += '<tr><td><strong>Price Range</strong></td><td>' + priceRange + '</td></tr>';
    html += '<tr><td><strong>Confidence</strong></td><td>' + confidence + '</td></tr>';
    if (q.booking_id) html += '<tr><td><strong>Booking ID</strong></td><td>' + escapeHtml(q.booking_id) + '</td></tr>';
    if (q.rim_count) html += '<tr><td><strong>Rim Count</strong></td><td>' + escapeHtml(String(q.rim_count)) + '</td></tr>';
    if (q.rim_size) html += '<tr><td><strong>Rim Size</strong></td><td>' + escapeHtml(String(q.rim_size)) + '"</td></tr>';
    if (q.created_at) html += '<tr><td><strong>Created</strong></td><td>' + formatDateTime(q.created_at) + '</td></tr>';

    if (q.breakdown && q.breakdown.length > 0) {
      html += '<tr><td colspan="2"><strong>Breakdown</strong></td></tr>';
      q.breakdown.forEach(function(item) {
        var label = item.item || item.label || '';
        var price = (item.per_rim_low != null && item.per_rim_high != null)
          ? ('$' + item.per_rim_low + '-$' + item.per_rim_high + '/rim x' + (item.quantity || 1))
          : ('$' + Number(item.amount || 0).toFixed(0));
        html += '<tr><td style="padding-left:20px">' + escapeHtml(label) + '</td><td>' + price + '</td></tr>';
      });
    }

    if (q.adjustments && q.adjustments.length > 0) {
      html += '<tr><td colspan="2"><strong>Adjustments</strong></td></tr>';
      q.adjustments.forEach(function(adj) {
        html += '<tr><td style="padding-left:20px" colspan="2">' + escapeHtml(String(adj)) + '</td></tr>';
      });
    }

    html += '</tbody></table>';
    body.innerHTML = html;
    body.className = '';
  }).catch(function(err) {
    var body = document.getElementById('quote-detail-body');
    if (body) body.innerHTML = 'Error: ' + escapeHtml(err.message);
  });
}

async function generateStandaloneQuote(event) {
  event.preventDefault();
  var form = document.getElementById('quote-form');
  if (!form) return;

  var serviceType = (document.getElementById('quote-service-type') || {}).value || '';
  var rimCount = (document.getElementById('quote-rim-count') || {}).value || '1';
  var rimSize = (document.getElementById('quote-rim-size') || {}).value || '';
  var damageDesc = (document.getElementById('quote-damage-desc') || {}).value || '';

  if (!serviceType) {
    showToast('Please select a service type.', 'warning');
    return;
  }

  var submitBtn = form.querySelector('button[type="submit"]');
  if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Generating...'; }

  try {
    var payload = {
      service_type: serviceType,
      rim_count: parseInt(rimCount, 10) || 1,
      damage_description: damageDesc
    };
    if (rimSize) payload.rim_size = parseFloat(rimSize);

    var res = await apiFetch('/api/quotes/generate', {
      method: 'POST',
      body: JSON.stringify(payload)
    });

    if (res && res.data) {
      var d = res.data;
      showToast('Quote generated: $' + d.estimate_low + ' - $' + d.estimate_high, 'success');
      form.reset();
      await loadQuotesList();
    } else {
      showToast('Failed to generate quote: ' + ((res && res.error) || 'Unknown error'), 'error');
    }
  } catch (err) {
    showToast('Error generating quote: ' + err.message, 'error');
  } finally {
    if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = 'Generate Quote'; }
  }
}
"""
