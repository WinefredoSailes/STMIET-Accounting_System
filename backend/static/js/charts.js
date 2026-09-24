/*
 * charts.js — Executive Dashboard chart rendering (Chart.js 4, UMD vendored).
 * Reads the data blob from the #dash-charts JSON script (json_script) injected
 * by ui/home/dashboard.html and paints the 4 Zone-B charts in the finance theme:
 *   brand teal (#0d9488), rose (#f43f5e), amber (#f59e0b), emerald (#10b981).
 */
(function () {
  'use strict';

  var el = document.getElementById('dash-charts');
  if (!el || !window.Chart) return;
  var data;
  try {
    data = JSON.parse(el.textContent);
  } catch (e) {
    return;
  }
  if (!data) return;

  var TEAL = '#0d9488';
  var TEAL_DARK = '#0f766e';
  var ROSE = '#f43f5e';
  var AMBER = '#f59e0b';
  var EMERALD = '#10b981';
  var INDIGO = '#6366f1';
  var SLATE_400 = '#a8a29e';
  var SLATE_500 = '#78716c';
  var SLATE_200 = '#e7e5e4';
  var PIE_PALETTE = [TEAL, ROSE, AMBER, EMERALD, INDIGO, '#14b8a6', '#f97316', SLATE_400];

  Chart.defaults.font.family = 'ui-sans-serif, system-ui, sans-serif';
  Chart.defaults.color = SLATE_400;

  function moneyTick(value) {
    if (Math.abs(value) >= 1000000) return '₱' + (value / 1000000).toFixed(1) + 'M';
    if (Math.abs(value) >= 1000) return '₱' + Math.round(value / 1000) + 'k';
    return '₱' + Math.round(value);
  }

  function pesos(ctx) {
    var v = typeof ctx.raw === 'number' ? ctx.raw : (ctx.parsed && ctx.parsed.y !== undefined ? ctx.parsed.y : 0);
    return ' ' + ctx.dataset.label + ': ₱' + v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  // Vertical gradient fill from a base color: strong near the line fading to
  // transparent. The gradient is created per-window so resizes stay correct.
  function areaGradient(ctx, rgba, rgbaFaded) {
    var chart = ctx.chart;
    var area = chart.chartArea;
    if (!area) return rgba;
    var g = ctx.createLinearGradient(0, area.top, 0, area.bottom);
    g.addColorStop(0, rgba);
    g.addColorStop(1, rgbaFaded);
    return g;
  }

  function lineOptions() {
    return {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          position: 'bottom',
          labels: { usePointStyle: true, pointStyle: 'circle', boxHeight: 7, padding: 14 },
        },
        tooltip: {
          backgroundColor: '#1c1917',
          padding: 10,
          cornerRadius: 8,
          titleFont: { weight: '600', size: 12 },
          bodyFont: { size: 11.5 },
          callbacks: { label: pesos },
        },
      },
      scales: {
        x: { grid: { display: false }, border: { color: SLATE_200 }, ticks: { font: { size: 11 }, maxRotation: 0 } },
        y: {
          grid: { color: SLATE_200 },
          border: { display: false },
          ticks: { font: { size: 11 }, callback: moneyTick, padding: 8 },
        },
      },
    };
  }

  function make(id, cfg) {
    var canvas = document.getElementById(id);
    if (canvas) new Chart(canvas.getContext('2d'), cfg);
  }

  var labels = data.month_labels || [];
  var segments = data.segment_codes || [];

  // 1. Revenue vs Expenses — dual area lines
  make('chart-rve', {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Revenue', data: data.revenue,
          borderColor: TEAL, borderWidth: 2.5, tension: 0.35,
          pointRadius: 3, pointHoverRadius: 5, pointBackgroundColor: '#fff', pointBorderColor: TEAL, pointBorderWidth: 2,
          fill: true,
          backgroundColor: function (c) { return areaGradient(c.chart.ctx, 'rgba(13,148,136,0.28)', 'rgba(13,148,136,0.02)'); },
        },
        {
          label: 'Expenses', data: data.expenses,
          borderColor: ROSE, borderWidth: 2.5, tension: 0.35,
          pointRadius: 3, pointHoverRadius: 5, pointBackgroundColor: '#fff', pointBorderColor: ROSE, pointBorderWidth: 2,
          fill: true,
          backgroundColor: function (c) { return areaGradient(c.chart.ctx, 'rgba(244,63,94,0.22)', 'rgba(244,63,94,0.02)'); },
        },
      ],
    },
    options: lineOptions(),
  });

  // 2. Cash flow — in vs out area lines
  make('chart-cashflow', {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Cash in', data: data.cash_in,
          borderColor: EMERALD, borderWidth: 2.5, tension: 0.35,
          pointRadius: 3, pointHoverRadius: 5, pointBackgroundColor: '#fff', pointBorderColor: EMERALD, pointBorderWidth: 2,
          fill: true,
          backgroundColor: function (c) { return areaGradient(c.chart.ctx, 'rgba(16,185,129,0.25)', 'rgba(16,185,129,0.02)'); },
        },
        {
          label: 'Cash out', data: data.cash_out,
          borderColor: AMBER, borderWidth: 2.5, tension: 0.35,
          pointRadius: 3, pointHoverRadius: 5, pointBackgroundColor: '#fff', pointBorderColor: AMBER, pointBorderWidth: 2,
          fill: true,
          backgroundColor: function (c) { return areaGradient(c.chart.ctx, 'rgba(245,158,11,0.25)', 'rgba(245,158,11,0.02)'); },
        },
      ],
    },
    options: lineOptions(),
  });

  // 3. Segment performance — grouped rounded bars
  make('chart-segments', {
    type: 'bar',
    data: {
      labels: segments,
      datasets: [
        {
          label: 'Revenue', data: data.segment_revenue,
          backgroundColor: TEAL, hoverBackgroundColor: TEAL_DARK,
          borderRadius: 6, borderSkipped: false, maxBarThickness: 40,
        },
        {
          label: 'Expenses', data: data.segment_expenses,
          backgroundColor: ROSE, hoverBackgroundColor: '#e11d48',
          borderRadius: 6, borderSkipped: false, maxBarThickness: 40,
        },
      ],
    },
    options: lineOptions(),
  });

  // 4. Expense breakdown — doughnut with center total + side bar legend
  var expenseTotal = (data.expense_values || []).reduce(function (a, b) { return a + b; }, 0);
  make('chart-expenses', {
    type: 'doughnut',
    data: {
      labels: data.expense_labels || [],
      datasets: [{
        data: data.expense_values || [],
        backgroundColor: PIE_PALETTE,
        borderWidth: 2,
        borderColor: '#ffffff',
        hoverOffset: 6,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '62%',
      plugins: {
        legend: {
          position: 'bottom',
          labels: { usePointStyle: true, pointStyle: 'circle', boxHeight: 7, padding: 12, font: { size: 11 } },
        },
        tooltip: {
          backgroundColor: '#1c1917',
          padding: 10,
          cornerRadius: 8,
          titleFont: { weight: '600', size: 12 },
          bodyFont: { size: 11.5 },
          callbacks: {
            label: function (ctx) {
              var total = ctx.dataset.data.reduce(function (a, b) { return a + b; }, 0) || 1;
              var pct = (ctx.raw / total * 100).toFixed(1);
              return ' ' + ctx.label + ': ₱' + ctx.raw.toLocaleString() + ' (' + pct + '%)';
            },
          },
        },
      },
    },
    plugins: [{
      id: 'doughnutCenter',
      beforeDraw: function (chart) {
        var meta = chart.getDatasetMeta(0);
        if (!meta.data.length) return;
        var x = meta.data[0].x;
        var y = meta.data[0].y;
        var ctx = chart.ctx;
        ctx.save();
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillStyle = SLATE_500;
        ctx.font = '600 10px ui-sans-serif, system-ui, sans-serif';
        ctx.fillText('TOTAL EXPENSES', x, y - 10);
        ctx.fillStyle = '#292524';
        ctx.font = '700 16px ui-sans-serif, system-ui, sans-serif';
        var compact = Math.abs(expenseTotal) >= 1000000
          ? '₱' + (expenseTotal / 1000000).toFixed(2) + 'M'
          : '₱' + expenseTotal.toLocaleString('en-US', { maximumFractionDigits: 0 });
        ctx.fillText(compact, x, y + 10);
        ctx.restore();
      },
    }],
  });
})();