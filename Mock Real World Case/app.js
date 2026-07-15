/* ═══════════════════════════════════
   Traditional NOC Anomaly Pipeline
   TechM Group 4 — app.js (Non-AI)
═══════════════════════════════════ */

// ── Live Clock (IST) ──
function updateClock() {
  const el = document.getElementById('live-clock');
  if (el) {
    const now = new Date();
    // Format to Indian Standard Time (IST)
    el.textContent = now.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false }) + ' IST';
  }
}
updateClock();
setInterval(updateClock, 1000);

// ── Incident Elapsed Timer (ticking up from 38:14) ──
let elapsedSeconds = 38 * 60 + 14;
function updateElapsed() {
  elapsedSeconds++;
  
  // Update main elapsed timer
  const mainEl = document.getElementById('elapsed');
  if (mainEl) {
    mainEl.textContent = formatDuration(elapsedSeconds);
  }
  
  // Update specific alert durations (fired offset from incident open)
  const dur1 = document.getElementById('dur1');
  if (dur1) dur1.textContent = formatDuration(elapsedSeconds - 6); // Fired at 14:22:06 (2s after open)
  
  const dur2 = document.getElementById('dur2');
  if (dur2) dur2.textContent = formatDuration(elapsedSeconds - 9); // Fired at 14:22:09 (5s after open)

  const dur3 = document.getElementById('dur3');
  if (dur3) dur3.textContent = formatDuration(elapsedSeconds - 18); // Fired at 14:22:18 (14s after open)
}
setInterval(updateElapsed, 1000);

function formatDuration(totalSecs) {
  if (totalSecs < 0) return "00:00:00";
  const hrs = String(Math.floor(totalSecs / 3600)).padStart(2, '0');
  const mins = String(Math.floor((totalSecs % 3600) / 60)).padStart(2, '0');
  const secs = String(totalSecs % 60).padStart(2, '0');
  return `${hrs}:${mins}:${secs}`;
}

// ── Tab Navigation ──
function show(tabName) {
  // Hide all panels
  const panels = document.querySelectorAll('.panel');
  panels.forEach(p => p.classList.remove('active'));
  
  // Deactivate all tabs
  const tabs = document.querySelectorAll('.tab');
  tabs.forEach(t => t.classList.remove('active'));
  
  // Show target panel and activate target tab
  const activePanel = document.getElementById(`p-${tabName}`);
  if (activePanel) activePanel.classList.add('active');
  
  const activeTab = document.getElementById(`t-${tabName}`);
  if (activeTab) activeTab.classList.add('active');
  
  // Redraw charts if graphic tabs are selected
  if (tabName === 'snmp' || tabName === 'netflow') {
    renderCharts();
  }
}

// ── Graph Rendering using HTML5 Canvas (Traditional Data Series) ──
function renderCharts() {
  drawBandwidthChart();
  drawNetFlowChart();
}

function drawBandwidthChart() {
  const canvas = document.getElementById('c-bw');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width;
  const h = canvas.height;
  
  // Clear canvas
  ctx.fillStyle = '#161b24';
  ctx.fillRect(0, 0, w, h);
  
  // Grid lines
  ctx.strokeStyle = '#2a3347';
  ctx.lineWidth = 1;
  for (let i = 1; i < 4; i++) {
    ctx.beginPath();
    ctx.moveTo(0, (h / 4) * i);
    ctx.lineTo(w, (h / 4) * i);
    ctx.stroke();
  }
  
  // Traditional static threshold line at 1.5 Gbps
  const thresholdY = h - (1.5 / 3.0) * h;
  ctx.strokeStyle = 'rgba(245, 101, 101, 0.6)';
  ctx.lineWidth = 1.5;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(0, thresholdY);
  ctx.lineTo(w, thresholdY);
  ctx.stroke();
  ctx.setLineDash([]);
  
  // Label for threshold
  ctx.fillStyle = '#f56565';
  ctx.font = '9px JetBrains Mono';
  ctx.fillText('SNMP Threshold: 1.5 Gbps', 10, thresholdY - 4);
  
  // Generate data: baseline ~0.4 Gbps, then spike at index 15 (14:22 IST) up to ~2.4 Gbps
  const points = [];
  const numPoints = 60;
  for (let i = 0; i < numPoints; i++) {
    if (i < 30) {
      points.push(0.35 + Math.random() * 0.1);
    } else if (i < 33) {
      // transient spike
      points.push(0.45 + (i - 30) * 0.5 + Math.random() * 0.15);
    } else {
      // sustained overload
      points.push(2.35 + Math.random() * 0.12);
    }
  }
  
  // Plot line
  ctx.strokeStyle = '#4299e1';
  ctx.lineWidth = 2;
  ctx.beginPath();
  for (let i = 0; i < points.length; i++) {
    const x = (i / (points.length - 1)) * w;
    const y = h - (points[i] / 3.0) * h; // scale max 3.0 Gbps
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();
  
  // Annotate spike time (14:22 IST)
  const spikeX = (30 / (points.length - 1)) * w;
  ctx.strokeStyle = 'rgba(237, 137, 54, 0.5)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(spikeX, 0);
  ctx.lineTo(spikeX, h);
  ctx.stroke();
  
  ctx.fillStyle = '#ed8936';
  ctx.fillText('14:22 IST (Spike)', spikeX + 5, 12);
}

function drawNetFlowChart() {
  const canvas = document.getElementById('c-flows');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width;
  const h = canvas.height;
  
  ctx.fillStyle = '#161b24';
  ctx.fillRect(0, 0, w, h);
  
  // Grid lines
  ctx.strokeStyle = '#2a3347';
  ctx.lineWidth = 1;
  for (let i = 1; i < 3; i++) {
    ctx.beginPath();
    ctx.moveTo(0, (h / 3) * i);
    ctx.lineTo(w, (h / 3) * i);
    ctx.stroke();
  }
  
  // Flows: normal established flow is low, SYN-only flows spike drastically at index 4 (14:20 IST)
  const numBuckets = 9; // 5-minute buckets from 14:00 to 14:40
  const establishedFlows = [450, 480, 510, 490, 420, 210, 180, 190, 205];
  const synOnlyFlows = [22, 18, 30, 25, 120000, 380000, 395000, 390000, 290000];
  
  // Max flows for scaling is 450,000
  const scaleMax = 450000;
  
  // Draw established flows (green)
  ctx.fillStyle = 'rgba(72, 187, 120, 0.6)';
  const barWidth = w / (numBuckets * 2);
  for (let i = 0; i < numBuckets; i++) {
    const x = (i * (w / numBuckets)) + barWidth / 2;
    const flowVal = establishedFlows[i];
    const barHeight = (flowVal / scaleMax) * h;
    const y = h - barHeight;
    ctx.fillRect(x, y, barWidth, barHeight);
  }
  
  // Draw SYN-only flows (red)
  ctx.fillStyle = 'rgba(245, 101, 101, 0.7)';
  for (let i = 0; i < numBuckets; i++) {
    const x = (i * (w / numBuckets)) + barWidth * 1.5;
    const flowVal = synOnlyFlows[i];
    const barHeight = (flowVal / scaleMax) * h;
    const y = h - barHeight;
    ctx.fillRect(x, y, barWidth, barHeight);
    
    // Label timestamps on x-axis
    ctx.fillStyle = '#60718a';
    ctx.font = '8px JetBrains Mono';
    const timeLabel = (14 + i * 5 >= 60) ? `15:${String((i*5)%60).padStart(2, '0')}` : `14:${String(i*5).padStart(2, '0')}`;
    if (i % 2 === 0) {
      ctx.fillText(timeLabel, x - 10, h - 2);
    }
  }
  
  // Labels for chart type
  ctx.fillStyle = '#68d391';
  ctx.font = '9px Inter';
  ctx.fillText('■ Established TCP Flows', 15, 15);
  ctx.fillStyle = '#fc8181';
  ctx.fillText('■ SYN-Only TCP Flows (S0/half-open)', 140, 15);
}

// Render initially on load
window.addEventListener('load', () => {
  renderCharts();
  
  // Periodically increment metrics slightly to simulate real-time polling updates
  setInterval(() => {
    if (document.getElementById('p-snmp').classList.contains('active')) {
      drawBandwidthChart();
    }
  }, 10000);
});
