// Admin stats console. Uses Chart.js (loaded via CDN in stats.html).
const $ = (s) => document.querySelector(s);
const api = async (p) => {
  const r = await fetch(p);
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json();
};

const TEAL = "#103e3a";
const ACCENT = "#cf563e";
const BLUE = "#3067a6";
const GREEN = "#2e7d32";
const YELLOW = "#ffb300";

let charts = {};
let catalog = {};
let allBiz = [], allMid = [], allSub = [];

function destroy(name) {
  if (charts[name]) { charts[name].destroy(); delete charts[name]; }
}

function makeBar(canvasId, labels, data, label, color, horizontal=false) {
  destroy(canvasId);
  const ctx = document.getElementById(canvasId);
  charts[canvasId] = new Chart(ctx, {
    type: "bar",
    data: { labels, datasets: [{ label, data, backgroundColor: color, borderRadius: 4 }] },
    options: {
      indexAxis: horizontal ? "y" : "x",
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: "#456", autoSkip: false, maxRotation: 60, minRotation: 30, font: { size: 10 } } },
        y: { ticks: { color: "#456" }, beginAtZero: true },
      },
    },
  });
}

function makeLine(canvasId, labels, data, label, color) {
  destroy(canvasId);
  const ctx = document.getElementById(canvasId);
  charts[canvasId] = new Chart(ctx, {
    type: "line",
    data: { labels, datasets: [{ label, data, borderColor: color, backgroundColor: color + "33",
      fill: true, tension: 0.3, pointRadius: 1.5, borderWidth: 2 }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { x: { ticks: { color: "#456", autoSkip: true, maxTicksLimit: 14 } }, y: { beginAtZero: true } },
    },
  });
}

async function loadCatalog() {
  catalog = await api("/api/catalog");
  allBiz = Object.keys(catalog).sort();
  $("#bizFilter").innerHTML = `<option value="">전체</option>` +
    allBiz.map(b => `<option>${b}</option>`).join("");
  $("#midFilter").innerHTML = `<option value="">전체</option>`;
}

function refreshMidOptions() {
  const biz = $("#bizFilter").value;
  const mids = biz ? Object.keys(catalog[biz] || {}).sort() : [];
  $("#midFilter").innerHTML = `<option value="">전체</option>` +
    mids.map(m => `<option>${m}</option>`).join("");
}

async function loadKPI() {
  const d = await api("/api/dashboard");
  $("#kpiTotal").textContent = d.total;
  $("#kpiToday").textContent = d.today;
  $("#kpiMonth").textContent = d.month;
  $("#kpiPending").textContent = d.pending;
  $("#kpiCompleted").textContent = d.completed;
}

async function loadBizChart() {
  const arr = await api("/api/stats/biz");
  arr.sort((a,b) => (b.avg_days ?? 0) - (a.avg_days ?? 0));
  makeBar("bizChart", arr.map(x => x.biz), arr.map(x => +(x.avg_days ?? 0).toFixed(1)),
    "평균 처리일수(일)", TEAL);
}

async function loadMidChart() {
  const biz = $("#bizFilter").value;
  const url = biz ? `/api/stats/mid?biz=${encodeURIComponent(biz)}` : "/api/stats/mid";
  const arr = await api(url);
  arr.sort((a,b) => (b.avg_days ?? 0) - (a.avg_days ?? 0));
  const top = arr.slice(0, 15);
  makeBar("midChart", top.map(x => x.mid), top.map(x => +(x.avg_days ?? 0).toFixed(1)),
    "평균 처리일수(일)", BLUE, true);
}

async function loadSubTable() {
  const biz = $("#bizFilter").value;
  const mid = $("#midFilter").value;
  const params = new URLSearchParams();
  if (biz) params.set("biz", biz);
  if (mid) params.set("mid", mid);
  const arr = await api(`/api/stats/sub${params.toString() ? "?"+params : ""}`);
  arr.sort((a,b) => (b.avg_days ?? 0) - (a.avg_days ?? 0));
  const tbody = document.querySelector("#subTable tbody");
  tbody.innerHTML = arr.slice(0, 80).map(x => `<tr>
    <td>${x.sub}</td>
    <td class="num">${x.avg_days?.toFixed(1) ?? "-"}</td>
    <td class="num">${x.median_days?.toFixed(1) ?? "-"}</td>
    <td class="num">${x.std_days?.toFixed(1) ?? "-"}</td>
    <td class="num">${x.n ?? "-"}</td>
  </tr>`).join("");
}

async function loadMonthly() {
  const arr = await api("/api/stats/monthly");
  // arr: [{ month: "2020-01", count: 1234 }, ...]
  makeLine("monthlyChart", arr.map(x => x.month), arr.map(x => x.count), "월 접수량", TEAL);
}

async function loadYearly() {
  const arr = await api("/api/stats/yearly");
  makeBar("yearlyChart", arr.map(x => x.year), arr.map(x => x.count), "연 접수량", ACCENT);
}

async function loadSeasonality() {
  const arr = await api("/api/stats/seasonality");
  // arr: [{ month: 1, count: ... }, ...] — normalize against mean
  if (!arr.length) return;
  const mean = arr.reduce((s,x) => s + x.count, 0) / arr.length;
  const labels = arr.map(x => `${x.month}월`);
  const data = arr.map(x => +(x.count / mean).toFixed(3));
  destroy("seasonalityChart");
  const ctx = document.getElementById("seasonalityChart");
  charts.seasonalityChart = new Chart(ctx, {
    type: "bar",
    data: { labels, datasets: [{ label: "혼잡 비율", data,
      backgroundColor: data.map(v => v >= 1.1 ? ACCENT : v >= 0.9 ? YELLOW : BLUE),
      borderRadius: 4 }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, suggestedMax: 1.5,
        ticks: { callback: v => v.toFixed(2) } } },
    },
  });
}

async function loadOpsCharts() {
  const apps = await api("/api/applications");
  // ops bar — biz × status
  const byBiz = {};
  for (const a of apps) {
    if (!a.biz) continue;
    byBiz[a.biz] = byBiz[a.biz] || { pending: 0, completed: 0 };
    byBiz[a.biz][a.status] = (byBiz[a.biz][a.status] || 0) + 1;
  }
  const labels = Object.keys(byBiz);
  destroy("opsChart");
  const ctx = document.getElementById("opsChart");
  charts.opsChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "pending", data: labels.map(l => byBiz[l].pending), backgroundColor: YELLOW, borderRadius: 4 },
        { label: "completed", data: labels.map(l => byBiz[l].completed), backgroundColor: GREEN, borderRadius: 4 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: true, position: "top" } },
      scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true } },
    },
  });

  // scatter — predicted vs actual
  const completed = apps.filter(a => a.completed_at && a.received_at && a.predicted_days != null);
  const points = completed.map(a => {
    const actual = (new Date(a.completed_at) - new Date(a.received_at)) / 86400000;
    return { x: a.predicted_days, y: +actual.toFixed(2), label: a.subcategory };
  });
  const maxV = Math.max(10, ...points.map(p => Math.max(p.x, p.y)));
  destroy("scatterChart");
  const ctx2 = document.getElementById("scatterChart");
  charts.scatterChart = new Chart(ctx2, {
    type: "scatter",
    data: {
      datasets: [
        { label: "실제 vs 예측", data: points, backgroundColor: ACCENT, pointRadius: 5 },
        { label: "perfect", type: "line", data: [{x:0,y:0},{x:maxV,y:maxV}],
          borderColor: "#aab", borderDash: [4,4], pointRadius: 0, fill: false },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: true },
        tooltip: { callbacks: { label: c => `${c.raw.label || ""} pred=${c.raw.x}일 actual=${c.raw.y}일` } },
      },
      scales: {
        x: { title: { display: true, text: "예측 처리일수" }, beginAtZero: true, max: maxV },
        y: { title: { display: true, text: "실제 처리일수" }, beginAtZero: true, max: maxV },
      },
    },
  });
}

async function refreshAll() {
  await Promise.all([
    loadKPI(),
    loadBizChart(),
    loadMidChart(),
    loadSubTable(),
    loadMonthly(),
    loadYearly(),
    loadSeasonality(),
    loadOpsCharts(),
    loadOutliers(),
    loadForecast(),
    loadHotspots(),
    loadBizHeat(),
    loadYoY(),
  ]);
}

// ------------------------------------------------------------ forecast
async function loadForecast() {
  const d = await api("/api/forecast/overall?horizon=6");
  if (!d.history?.length) return;
  const histTail = d.history.slice(-12);
  const labels = [...histTail.map(h => h.ym), ...d.forecast.map(f => f.ym)];
  const histData = [...histTail.map(h => h.count), ...d.forecast.map(() => null)];
  const fcData = [...histTail.map(() => null), ...d.forecast.map(f => f.predicted)];
  const lowData = [...histTail.map(() => null), ...d.forecast.map(f => f.low)];
  const highData = [...histTail.map(() => null), ...d.forecast.map(f => f.high)];

  document.getElementById("forecastSummary").innerHTML =
    `최근 12개월 평균(deseasoned): <b>${d.level}</b>건/월 · ` +
    `백테스트 MAE: <b>${d.backtest_mae ?? "-"}</b>건 · ` +
    `다음 6개월 중 성수기(<b>×1.10+</b>): ${d.forecast.filter(f => f.is_peak).map(f => f.ym).join(", ") || "없음"}`;

  destroy("forecastChart");
  charts.forecastChart = new Chart(document.getElementById("forecastChart"), {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "실제", data: histData, borderColor: TEAL, backgroundColor: TEAL+"22",
          fill: false, tension: 0.3, pointRadius: 2, borderWidth: 2 },
        { label: "예측", data: fcData, borderColor: ACCENT, backgroundColor: ACCENT+"33",
          fill: false, tension: 0.3, pointRadius: 4, borderWidth: 2.5, borderDash: [4,4] },
        { label: "low (10%)", data: lowData, borderColor: ACCENT+"55",
          backgroundColor: ACCENT+"22", fill: "+1", pointRadius: 0, borderWidth: 0 },
        { label: "high (90%)", data: highData, borderColor: ACCENT+"55",
          backgroundColor: ACCENT+"22", fill: false, pointRadius: 0, borderWidth: 0 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: true, position: "top",
        labels: { filter: it => !["low (10%)","high (90%)"].includes(it.text) } } },
      scales: { x: { ticks: { color: "#456" } }, y: { beginAtZero: true } },
    },
  });
}

// ------------------------------------------------------------ hotspots
async function loadHotspots() {
  const d = await api("/api/forecast/hotspots?top_k=12");
  const monthLabel = `${d.next_month}월`;
  const tbody = document.querySelector("#hotspotTable tbody");
  tbody.innerHTML = d.rows.map((r, i) => `<tr ${r.alert ? 'style="background:#ffe5e5;"' : ""}>
    <td>${i+1}</td>
    <td>${r.biz}</td>
    <td>${r.mid}</td>
    <td class="num">${r.current_ratio.toFixed(2)}×</td>
    <td class="num"><b>${r.next_ratio.toFixed(2)}×</b></td>
    <td class="num">${r.next_count.toLocaleString()}건</td>
    <td class="num">${r.total.toLocaleString()}</td>
    <td>${r.alert ? `<span style="color:#c62828; font-weight:700;">⚠ ${monthLabel} 성수기</span>` : `<span style="color:#789;">평년 수준</span>`}</td>
  </tr>`).join("") || `<tr><td colspan="8">데이터 없음</td></tr>`;
}

// ------------------------------------------------------------ biz seasonal heatmap
async function loadBizHeat() {
  const arr = await api("/api/forecast/biz-heat");
  if (!arr.length) return;
  const months = Array.from({length:12}, (_,i)=>i+1);
  // build header
  const headHTML = `<div class="h-cell h-label">사업구분</div>` +
    months.map(m => `<div class="h-cell" style="background:#103e3a; color:#fff;">${m}월</div>`).join("");
  // gradient: 0% white -> 20% deep teal
  const cellColor = (pct) => {
    const p = Math.min(1, pct / 20);
    const r = Math.round(255 - (255-16)*p);
    const g = Math.round(255 - (255-62)*p);
    const b = Math.round(255 - (255-58)*p);
    return `rgb(${r},${g},${b})`;
  };
  const rowsHTML = arr.map(row => {
    const cells = months.map(m => {
      const v = row.months[m] || 0;
      const c = cellColor(v);
      const txtColor = v > 12 ? "#fff" : "#234";
      return `<div class="h-cell" style="background:${c}; color:${txtColor};" title="${row.biz} ${m}월: ${v}%">${v.toFixed(0)}</div>`;
    }).join("");
    return `<div class="h-cell h-label" style="font-weight:600;">${row.biz}</div>${cells}`;
  }).join("");
  document.getElementById("heatBox").innerHTML =
    `<div class="heatmap">${headHTML}${rowsHTML}</div>`;
}

// ------------------------------------------------------------ yoy
async function loadYoY() {
  const arr = await api("/api/forecast/biz-yoy");
  if (!arr.length) return;
  const labels = arr.map(r => r.biz);
  const data = arr.map(r => r.growth == null ? 0 : Math.round(r.growth * 1000) / 10); // %
  const colors = data.map(v => v >= 0 ? GREEN : ACCENT);
  destroy("yoyChart");
  charts.yoyChart = new Chart(document.getElementById("yoyChart"), {
    type: "bar",
    data: { labels, datasets: [{ label: "YoY 성장률(%)", data, backgroundColor: colors, borderRadius: 4 }] },
    options: {
      indexAxis: "y",
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: {
          label: c => {
            const r = arr[c.dataIndex];
            return `${r.prev_year}: ${r.prev.toLocaleString()} → ${r.curr_year}: ${r.curr.toLocaleString()} (${data[c.dataIndex]}%)`;
          },
        } },
      },
      scales: {
        x: { ticks: { callback: v => v + "%" } },
      },
    },
  });
}

function bind() {
  $("#bizFilter").addEventListener("input", () => {
    refreshMidOptions();
    Promise.all([loadMidChart(), loadSubTable()]);
  });
  $("#midFilter").addEventListener("input", () => loadSubTable());
}

async function loadOutliers() {
  try {
    const d = await api("/api/alerts");
    const tbody = document.querySelector("#outlierTable tbody");
    const sum = document.getElementById("outlierSummary");
    if (!tbody) return;
    const rows = d.outliers || [];
    sum.textContent = `이상치 ${d.counts.outliers}건 / 지연 ${d.counts.overdue}건 / 임박 ${d.counts.due_soon}건`;
    if (rows.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" style="padding:12px; text-align:center; color:#789;">이상치 없음 (예측 정확도 양호)</td></tr>`;
      return;
    }
    tbody.innerHTML = rows.map(r => {
      const diff = (r.actual_days - r.predicted_days).toFixed(1);
      return `<tr style="border-top:1px solid #f4d4d0;"><td style="padding:5px 6px;">#${r.id}</td><td>${r.category||""}</td><td>${r.sample||""}</td><td style="text-align:right;">${r.predicted_days}</td><td style="text-align:right;">${r.actual_days}</td><td style="text-align:right; color:${diff>0?'#c62828':'#2e7d32'};">${diff>0?"+":""}${diff}</td><td style="text-align:right;"><b>${r.z}</b></td></tr>`;
    }).join("");
  } catch (e) { console.warn("outliers", e); }
}

(async function init() {
  await loadCatalog();
  bind();
  await refreshAll();
})();

// ------------------------------------------------------------ TestMate Pro: bottleneck forecast + assignment simulation
(function initOpsAiCards() {
  function esc(v) {
    return String(v ?? "").replace(/[&<>"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]));
  }
  function mountCards() {
    const grid = document.querySelector(".grid");
    if (!grid || document.getElementById("bottleneckTable")) return;
    grid.insertAdjacentHTML("afterbegin", `
      <div class="card full" style="background:#eef8f6; border-left:4px solid #126b67;">
        <h3>TestMate Pro · 관리자용 병목 예측</h3>
        <div class="sub">미완료 신청, 과거 처리 편차, 예상 처리일을 결합해 병목 후보를 산출합니다.</div>
        <div id="bottleneckSummary" style="font-size:12.5px; color:#234; margin-bottom:8px;">분석 중...</div>
        <div style="overflow-x:auto;">
          <table class="mini" id="bottleneckTable">
            <thead><tr><th>#</th><th>사업구분</th><th>중분류</th><th class="num">대기</th><th class="num">예상일</th><th class="num">편차</th><th>위험</th><th>권고</th></tr></thead>
            <tbody></tbody>
          </table>
        </div>
      </div>
      <div class="card full" style="background:#f5f1ff; border-left:4px solid #6b5b95;">
        <h3>TestMate Pro · 업무 배정 시뮬레이션</h3>
        <div class="sub">담당자 추가, 일일 처리량, 고위험 우선 처리 건수를 바꿔 예상 해소 기간을 비교합니다.</div>
        <div class="sim-form" style="display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:8px; align-items:end; margin:8px 0 10px;">
          <label>현재 담당자<input id="simStaff" type="number" min="1" value="5" style="min-height:34px;" /></label>
          <label>추가 담당자<input id="simExtra" type="number" min="0" value="1" style="min-height:34px;" /></label>
          <label>1인 처리량<input id="simCapacity" type="number" min="0.1" step="0.1" value="1" style="min-height:34px;" /></label>
          <label>우선 처리<input id="simExpedite" type="number" min="0" value="5" style="min-height:34px;" /></label>
          <button id="simButton" type="button" style="min-height:36px; border:0; border-radius:6px; background:#6b5b95; color:#fff; font-weight:800;">시뮬레이션</button>
        </div>
        <div id="simulationResult" style="display:grid; gap:6px; font-size:13px; color:#234;">조건을 입력하고 시뮬레이션을 실행하세요.</div>
      </div>`);
    document.getElementById("simButton").addEventListener("click", runSimulation);
  }
  async function loadBottlenecks() {
    mountCards();
    const tbody = document.querySelector("#bottleneckTable tbody");
    const summary = document.getElementById("bottleneckSummary");
    if (!tbody || !summary) return;
    try {
      const d = await api("/api/ops/bottlenecks?top_k=8");
      summary.textContent = d.summary;
      tbody.innerHTML = (d.rows || []).map((r, i) => `<tr>
        <td>${i + 1}</td><td>${esc(r.biz)}</td><td>${esc(r.mid)}</td>
        <td class="num">${r.pending}</td><td class="num">${r.avg_predicted_days}</td><td class="num">${r.history_std}</td>
        <td><b style="color:${r.risk_label === "높음" ? "#c62828" : r.risk_label === "주의" ? "#a66b00" : "#2e7d32"};">${esc(r.risk_label)}</b></td>
        <td>${esc(r.recommended_action)}</td></tr>`).join("") || `<tr><td colspan="8">미완료 신청이 없어 병목 후보가 없습니다.</td></tr>`;
    } catch (e) {
      summary.textContent = "병목 예측 실패: " + e.message;
    }
  }
  async function runSimulation() {
    const box = document.getElementById("simulationResult");
    if (!box) return;
    box.textContent = "시뮬레이션 계산 중...";
    const payload = {
      staff_current: Number(document.getElementById("simStaff").value || 5),
      staff_extra: Number(document.getElementById("simExtra").value || 0),
      daily_capacity: Number(document.getElementById("simCapacity").value || 1),
      expedite_count: Number(document.getElementById("simExpedite").value || 0),
    };
    try {
      const r = await api("/api/ops/simulate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      box.innerHTML = `
        <div><b>현재:</b> 담당자 ${r.before.staff}명 · 예상 해소 ${r.before.estimated_clearance_days}일</div>
        <div><b>개선:</b> 담당자 ${r.after.staff}명 · 고위험 ${r.after.expedite_count}건 우선 · 예상 해소 ${r.after.estimated_clearance_days}일</div>
        <div><b>효과:</b> ${r.effect.reduced_days}일 단축 · ${r.effect.reduction_percent}% 개선</div>
        <div style="color:#6b5b95; font-weight:800;">${esc(r.recommendation)}</div>`;
    } catch (e) {
      box.textContent = "시뮬레이션 실패: " + e.message;
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => { mountCards(); loadBottlenecks(); });
  else { mountCards(); loadBottlenecks(); }
})();
