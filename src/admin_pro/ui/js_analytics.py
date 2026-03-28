"""
admin_pro/ui/js_analytics.py
Analytics section JavaScript for the Admin Pro dashboard.
Chart.js is loaded from CDN in the HTML head.
"""

JS_ANALYTICS = """
// ---------------------------------------------------------------------------
// Chart.js global defaults
// ---------------------------------------------------------------------------
Chart.defaults.color = '#64748b';
Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";

// ---------------------------------------------------------------------------
// Colour palette
// ---------------------------------------------------------------------------
const CHART_COLORS = {
  blue:   '#3b82f6',
  green:  '#22c55e',
  amber:  '#f59e0b',
  red:    '#ef4444',
  purple: '#8b5cf6',
  teal:   '#14b8a6',
  orange: '#f97316',
  muted:  '#64748b',
};
const CHART_BG = 'rgba(255,255,255,0.05)';

// ---------------------------------------------------------------------------
// Shared grid / tick style helpers
// ---------------------------------------------------------------------------
const GRID_STYLE  = { color: 'rgba(255,255,255,0.05)' };
const TICK_STYLE  = { color: '#64748b' };
const BASE_TOOLTIP = {
  backgroundColor: 'rgba(15,23,42,0.9)',
  titleColor: '#f1f5f9',
  bodyColor: '#cbd5e1',
  borderColor: 'rgba(255,255,255,0.1)',
  borderWidth: 1,
  padding: 10,
  cornerRadius: 6,
};

// ---------------------------------------------------------------------------
// Chart cleanup
// ---------------------------------------------------------------------------
function destroyChart(key) {
  if (APP.charts[key]) {
    APP.charts[key].destroy();
    delete APP.charts[key];
  }
}

// ---------------------------------------------------------------------------
// Service label helper  (mirrors Python SERVICE_LABELS)
// ---------------------------------------------------------------------------
function serviceLabel(type) {
  const MAP = {
    rim_repair:    'Rim Repair',
    paint_touchup: 'Paint Touch-up',
    multiple_rims: 'Multiple Rims',
  };
  return MAP[type] || (type || 'Unknown').replace(/_/g, ' ').replace(/\\b\\w/g, c => c.toUpperCase());
}

// ---------------------------------------------------------------------------
// Trend week selector state
// ---------------------------------------------------------------------------
let _trendsWeeks = 8;

function setTrendsWeeks(weeks) {
  _trendsWeeks = weeks;
  // Update active button highlight
  document.querySelectorAll('.ap-trend-btn').forEach(btn => {
    btn.classList.toggle('ap-btn-active', parseInt(btn.dataset.weeks, 10) === weeks || (weeks === 0 && btn.dataset.weeks === 'all'));
  });
  loadTrendsChart();
}

// ---------------------------------------------------------------------------
// Analytics Overview KPIs
// ---------------------------------------------------------------------------
async function loadAnalyticsOverview() {
  try {
    const data = await apiFetch('/v2/api/analytics/overview');
    const d = data;

    const conversionEl = document.getElementById('ana-conversion');
    if (conversionEl) {
      conversionEl.textContent = (d.conversion_rate ?? 0).toFixed(1) + '%';
    }

    const avgConfirmEl = document.getElementById('ana-avg-confirm');
    if (avgConfirmEl) {
      const hours = d.avg_confirm_hours ?? 0;
      if (hours < 1) {
        avgConfirmEl.textContent = Math.round(hours * 60) + 'm';
      } else if (hours < 24) {
        avgConfirmEl.textContent = Math.round(hours) + 'h';
      } else {
        avgConfirmEl.textContent = (hours / 24).toFixed(1) + 'd';
      }
    }

    const weekEl = document.getElementById('ana-week');
    if (weekEl) {
      weekEl.textContent = d.this_week_confirmed ?? 0;
    }

    const revenueEl = document.getElementById('ana-revenue');
    if (revenueEl) {
      // Estimated revenue = confirmed * avg price; real breakdown comes from revenue endpoint
      // Show confirmed count here; revenue card handles dollar value
      revenueEl.textContent = d.confirmed ?? 0;
    }
  } catch (err) {
    console.error('loadAnalyticsOverview error:', err);
  }
}

// ---------------------------------------------------------------------------
// Bookings Trend Line Chart
// ---------------------------------------------------------------------------
async function loadTrendsChart() {
  try {
    const weeksParam = _trendsWeeks > 0 ? _trendsWeeks : 52;
    const data = await apiFetch(`/v2/api/analytics/trends?weeks=${weeksParam}`);
    const d = data;

    destroyChart('trends');

    const canvas = document.getElementById('chart-trends');
    if (!canvas) return;

    APP.charts['trends'] = new Chart(canvas, {
      type: 'line',
      data: {
        labels: d.labels,
        datasets: [{
          label: 'Confirmed Bookings',
          data: d.counts,
          borderColor: CHART_COLORS.blue,
          backgroundColor: 'rgba(59,130,246,0.1)',
          fill: true,
          tension: 0.4,
          pointBackgroundColor: CHART_COLORS.blue,
          pointBorderColor: CHART_COLORS.blue,
          pointRadius: 4,
          pointHoverRadius: 6,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            ...BASE_TOOLTIP,
            callbacks: {
              title: ctx => ctx[0].label,
              label: ctx => ` ${ctx.parsed.y} booking${ctx.parsed.y !== 1 ? 's' : ''}`,
            },
          },
        },
        scales: {
          x: {
            grid: GRID_STYLE,
            ticks: {
              ...TICK_STYLE,
              maxRotation: 30,
              autoSkip: true,
              maxTicksLimit: 8,
            },
          },
          y: {
            grid: GRID_STYLE,
            ticks: { ...TICK_STYLE, stepSize: 1 },
            beginAtZero: true,
          },
        },
        interaction: {
          mode: 'index',
          intersect: false,
        },
      },
    });
  } catch (err) {
    console.error('loadTrendsChart error:', err);
  }
}

// ---------------------------------------------------------------------------
// Service Type Doughnut Chart
// ---------------------------------------------------------------------------
async function loadServicesChart() {
  try {
    const data = await apiFetch('/v2/api/analytics/services');
    const services = data.services || [];

    destroyChart('services');

    const canvas = document.getElementById('chart-services');
    if (!canvas) return;

    const palette = [
      CHART_COLORS.blue,
      CHART_COLORS.green,
      CHART_COLORS.amber,
      CHART_COLORS.purple,
      CHART_COLORS.teal,
      CHART_COLORS.orange,
      CHART_COLORS.red,
    ];

    const labels = services.map(s => s.label || serviceLabel(s.type));
    const counts  = services.map(s => s.count);
    const colors  = services.map((_, i) => palette[i % palette.length]);

    APP.charts['services'] = new Chart(canvas, {
      type: 'doughnut',
      data: {
        labels,
        datasets: [{
          data: counts,
          backgroundColor: colors,
          borderColor: 'rgba(15,23,42,0.8)',
          borderWidth: 2,
          hoverOffset: 6,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '60%',
        plugins: {
          legend: {
            display: true,
            position: 'bottom',
            labels: {
              color: '#94a3b8',
              padding: 12,
              boxWidth: 12,
              font: { size: 12 },
            },
          },
          tooltip: {
            ...BASE_TOOLTIP,
            callbacks: {
              label: ctx => {
                const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                const pct   = total ? ((ctx.parsed / total) * 100).toFixed(1) : 0;
                return ` ${ctx.label}: ${ctx.parsed} (${pct}%)`;
              },
            },
          },
        },
      },
    });
  } catch (err) {
    console.error('loadServicesChart error:', err);
  }
}

// ---------------------------------------------------------------------------
// Conversion Funnel Horizontal Bar Chart
// ---------------------------------------------------------------------------
async function loadFunnelChart() {
  try {
    const data = await apiFetch('/v2/api/analytics/funnel');
    const stages = (data.stages || []).slice().reverse(); // bottom-to-top for horizontal bar

    destroyChart('funnel');

    const canvas = document.getElementById('chart-funnel');
    if (!canvas) return;

    const stageColors = [
      CHART_COLORS.blue,
      CHART_COLORS.teal,
      CHART_COLORS.amber,
      CHART_COLORS.green,
      CHART_COLORS.purple,
    ];

    // Top of funnel for percentage calculation (first stage in original order = last after reverse)
    const topCount = stages.length ? stages[stages.length - 1].count : 1;

    const labels   = stages.map(s => s.label);
    const counts   = stages.map(s => s.count);
    const bgColors = stages.map((_, i) => stageColors[i % stageColors.length]);

    APP.charts['funnel'] = new Chart(canvas, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: 'Count',
          data: counts,
          backgroundColor: bgColors,
          borderColor: bgColors,
          borderWidth: 1,
          borderRadius: 4,
          borderSkipped: false,
        }],
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            ...BASE_TOOLTIP,
            callbacks: {
              label: ctx => {
                const count = ctx.parsed.x;
                const pct   = topCount ? ((count / topCount) * 100).toFixed(1) : 0;
                return ` ${count.toLocaleString()} (${pct}% of total)`;
              },
            },
          },
        },
        scales: {
          x: {
            grid: GRID_STYLE,
            ticks: TICK_STYLE,
            beginAtZero: true,
          },
          y: {
            grid: { display: false },
            ticks: { ...TICK_STYLE, font: { size: 12 } },
          },
        },
      },
    });
  } catch (err) {
    console.error('loadFunnelChart error:', err);
  }
}

// ---------------------------------------------------------------------------
// Top Suburbs Horizontal Bar Chart
// ---------------------------------------------------------------------------
async function loadSuburbsChart() {
  try {
    const data = await apiFetch('/v2/api/analytics/suburbs');
    const suburbs = (data.suburbs || []).slice(0, 10).reverse(); // flip for horizontal bar readability

    destroyChart('suburbs');

    const canvas = document.getElementById('chart-suburbs');
    if (!canvas) return;

    const maxCount = suburbs.length ? Math.max(...suburbs.map(s => s.count)) : 1;

    // Single-hue gradient: brightest bar = highest count
    const bgColors = suburbs.map(s => {
      const opacity = 0.35 + 0.65 * (s.count / maxCount);
      return `rgba(59,130,246,${opacity.toFixed(2)})`;
    });

    APP.charts['suburbs'] = new Chart(canvas, {
      type: 'bar',
      data: {
        labels: suburbs.map(s => s.name),
        datasets: [{
          label: 'Bookings',
          data: suburbs.map(s => s.count),
          backgroundColor: bgColors,
          borderColor: CHART_COLORS.blue,
          borderWidth: 1,
          borderRadius: 4,
          borderSkipped: false,
        }],
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            ...BASE_TOOLTIP,
            callbacks: {
              label: ctx => ` ${ctx.parsed.x} booking${ctx.parsed.x !== 1 ? 's' : ''}`,
            },
          },
        },
        scales: {
          x: {
            grid: GRID_STYLE,
            ticks: { ...TICK_STYLE, stepSize: 1 },
            beginAtZero: true,
          },
          y: {
            grid: { display: false },
            ticks: { ...TICK_STYLE, font: { size: 12 } },
          },
        },
      },
    });
  } catch (err) {
    console.error('loadSuburbsChart error:', err);
  }
}

// ---------------------------------------------------------------------------
// Revenue Card
// ---------------------------------------------------------------------------
async function loadRevenueCard() {
  try {
    const data = await apiFetch('/v2/api/analytics/revenue');
    const d = data;

    const el = document.getElementById('ana-revenue-detail');
    if (!el) return;

    const byServiceRows = (d.by_service || []).map(s => `
      <div class="ap-flex ap-flex-between ap-mt-8">
        <span>${serviceLabel(s.type)}</span>
        <span class="ap-text-muted">$${(s.revenue || 0).toLocaleString()} (${s.count})</span>
      </div>
    `).join('');

    el.innerHTML = `
      <div class="ap-kpi-value" style="color:var(--ap-green)">$${(d.total_estimated || 0).toLocaleString()}</div>
      <div class="ap-text-muted">Estimated (AUD)</div>
      <div class="ap-mt-16">
        ${byServiceRows || '<div class="ap-text-muted">No confirmed bookings yet.</div>'}
      </div>
    `;
  } catch (err) {
    console.error('loadRevenueCard error:', err);
    const el = document.getElementById('ana-revenue-detail');
    if (el) el.innerHTML = '<div class="ap-text-muted">Could not load revenue data.</div>';
  }
}

// ---------------------------------------------------------------------------
// Date range filter buttons — rendered inline in the analytics HTML section
// Call this after the analytics panel HTML is in the DOM
// ---------------------------------------------------------------------------
function initTrendsWeekSelector() {
  const container = document.getElementById('trends-week-selector');
  if (!container) return;

  const options = [
    { label: '4w',  weeks: 4  },
    { label: '8w',  weeks: 8  },
    { label: '12w', weeks: 12 },
    { label: 'All', weeks: 0  },
  ];

  container.innerHTML = options.map(opt => `
    <button
      class="ap-btn ap-btn-sm ap-trend-btn${opt.weeks === _trendsWeeks ? ' ap-btn-active' : ''}"
      data-weeks="${opt.weeks === 0 ? 'all' : opt.weeks}"
      onclick="setTrendsWeeks(${opt.weeks})"
    >${opt.label}</button>
  `).join('');
}

// ---------------------------------------------------------------------------
// Main init — called from the dashboard router when the analytics tab opens
// ---------------------------------------------------------------------------
async function initAnalytics() {
  // Reset trend week selector to default if this is a fresh open
  initTrendsWeekSelector();

  await Promise.all([
    loadAnalyticsOverview(),
    loadTrendsChart(),
    loadServicesChart(),
    loadFunnelChart(),
    loadSuburbsChart(),
    loadRevenueCard(),
  ]);
}
"""
