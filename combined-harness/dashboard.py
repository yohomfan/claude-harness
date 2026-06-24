#!/usr/bin/env python3
"""
Dashboard — Web-based monitoring for the combined harness
==========================================================

Usage:
    python dashboard.py <project-dir> [--port 8077]

Opens a local HTTP server. Visit http://localhost:8077 to see:
- Current status (iteration, phase, pass rate, elapsed time)
- Pass rate trend chart
- Evaluator verdict timeline
- Feature list with pass/fail filter
- Git commit timeline
"""

import argparse
import json
import subprocess
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

from tracker import read_status, read_history


def get_features(project_dir: Path) -> list:
    path = project_dir / "feature_list.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def get_git_log(project_dir: Path, n: int = 30) -> list[dict]:
    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={n}", "--format=%H|%ai|%s"],
            cwd=str(project_dir),
            capture_output=True, timeout=5,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0 or not result.stdout:
            return []
        entries = []
        for line in result.stdout.strip().split("\n"):
            if "|" in line:
                parts = line.split("|", 2)
                entries.append({"hash": parts[0][:8], "date": parts[1].strip(), "message": parts[2].strip()})
        return entries
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, UnicodeDecodeError):
        return []


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Claude Harness Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  :root {
    --bg: #0f172a; --surface: #1e293b; --border: #334155;
    --text: #e2e8f0; --muted: #94a3b8; --accent: #818cf8;
    --green: #34d399; --red: #f87171; --yellow: #fbbf24;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Inter', system-ui, sans-serif; background: var(--bg); color: var(--text); padding: 20px; }
  h1 { font-size: 20px; margin-bottom: 16px; color: var(--accent); }
  h2 { font-size: 15px; color: var(--muted); margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.5px; }

  .grid { display: grid; gap: 16px; }
  .grid-top { grid-template-columns: repeat(5, 1fr); }
  .grid-mid { grid-template-columns: 1fr 1fr; }
  .grid-bot { grid-template-columns: 1fr 1fr; }
  @media (max-width: 900px) { .grid-top, .grid-mid, .grid-bot { grid-template-columns: 1fr; } }

  .card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 16px;
  }
  .stat-value { font-size: 28px; font-weight: 700; }
  .stat-label { font-size: 12px; color: var(--muted); margin-top: 4px; }

  .progress-bar { height: 8px; background: var(--border); border-radius: 4px; margin-top: 8px; overflow: hidden; }
  .progress-fill { height: 100%; background: var(--green); border-radius: 4px; transition: width 0.5s; }

  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }
  .badge-pass { background: rgba(52,211,153,0.2); color: var(--green); }
  .badge-fail { background: rgba(248,113,113,0.2); color: var(--red); }
  .badge-phase { background: rgba(129,140,248,0.2); color: var(--accent); }
  .badge-paused { background: rgba(251,191,36,0.2); color: var(--yellow); }

  .timeline { max-height: 400px; overflow-y: auto; }
  .timeline-item { padding: 8px 0; border-bottom: 1px solid var(--border); font-size: 13px; }
  .timeline-item:last-child { border-bottom: none; }
  .timeline-meta { color: var(--muted); font-size: 11px; margin-top: 2px; }
  .findings { color: var(--muted); font-size: 12px; margin-top: 4px; white-space: pre-wrap; }

  .feature-list { max-height: 400px; overflow-y: auto; }
  .feature-item { padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 13px; display: flex; align-items: center; gap: 8px; }
  .feature-item:last-child { border-bottom: none; }

  .filter-bar { margin-bottom: 10px; display: flex; gap: 8px; }
  .filter-btn { background: var(--border); border: none; color: var(--text); padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; }
  .filter-btn.active { background: var(--accent); }

  .chart-container { position: relative; height: 260px; }

  .git-list { max-height: 400px; overflow-y: auto; }
  .git-item { padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 13px; }
  .git-hash { color: var(--accent); font-family: monospace; font-size: 12px; }
  .git-date { color: var(--muted); font-size: 11px; }

  .refresh-note { color: var(--muted); font-size: 11px; text-align: right; margin-bottom: 8px; }
</style>
</head>
<body>

<h1>Claude Harness Dashboard</h1>
<div class="refresh-note" id="refreshNote">Auto-refresh: 5s</div>

<!-- Status cards -->
<div class="grid grid-top" id="statusCards">
  <div class="card"><div class="stat-value" id="sIteration">-</div><div class="stat-label">Iteration</div></div>
  <div class="card"><div class="stat-value"><span class="badge badge-phase" id="sPhase">-</span></div><div class="stat-label">Phase</div></div>
  <div class="card">
    <div class="stat-value" id="sPassRate">-</div><div class="stat-label">Pass Rate</div>
    <div class="progress-bar"><div class="progress-fill" id="sProgressFill"></div></div>
  </div>
  <div class="card"><div class="stat-value" id="sElapsed">-</div><div class="stat-label">Elapsed</div></div>
  <div class="card"><div class="stat-value" id="sStall">-</div><div class="stat-label">Consecutive Stall</div></div>
</div>

<!-- Charts + Timeline -->
<div class="grid grid-mid" style="margin-top:16px">
  <div class="card">
    <h2>Pass Rate Trend</h2>
    <div class="chart-container"><canvas id="trendChart"></canvas></div>
  </div>
  <div class="card">
    <h2>Evaluator Verdicts</h2>
    <div class="timeline" id="verdictTimeline"></div>
  </div>
</div>

<!-- Features + Git -->
<div class="grid grid-bot" style="margin-top:16px">
  <div class="card">
    <h2>Features</h2>
    <div class="filter-bar">
      <button class="filter-btn active" onclick="setFilter('all')">All</button>
      <button class="filter-btn" onclick="setFilter('pass')">Passing</button>
      <button class="filter-btn" onclick="setFilter('fail')">Failing</button>
    </div>
    <div class="feature-list" id="featureList"></div>
  </div>
  <div class="card">
    <h2>Git Commits</h2>
    <div class="git-list" id="gitList"></div>
  </div>
</div>

<script>
let trendChart = null;
let currentFilter = 'all';

function fmt(s) {
  if (s == null) return '-';
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
}

function setFilter(f) {
  currentFilter = f;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.toggle('active', b.textContent.toLowerCase().includes(f === 'all' ? 'all' : f)));
  renderFeatures(window._features || []);
}

function renderStatus(data) {
  if (!data) return;
  document.getElementById('sIteration').textContent = data.iteration || 0;
  const phaseEl = document.getElementById('sPhase');
  phaseEl.textContent = data.phase || '-';
  phaseEl.className = 'badge ' + (data.paused ? 'badge-paused' : 'badge-phase');
  if (data.paused) phaseEl.textContent = 'PAUSED';

  const pct = data.total > 0 ? ((data.passing / data.total) * 100).toFixed(1) : '0';
  document.getElementById('sPassRate').textContent = `${data.passing}/${data.total} (${pct}%)`;
  document.getElementById('sProgressFill').style.width = pct + '%';
  document.getElementById('sElapsed').textContent = fmt(data.elapsed_seconds);
  document.getElementById('sStall').textContent = data.consecutive_stall || 0;
}

function renderTrend(history) {
  const ctx = document.getElementById('trendChart').getContext('2d');
  const labels = history.map(h => `#${h.iteration}`);
  const passData = history.map(h => h.total > 0 ? ((h.passing / h.total) * 100) : 0);
  const buildData = history.map(h => h.build_seconds || 0);

  if (trendChart) trendChart.destroy();
  trendChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Pass %',
          data: passData,
          borderColor: '#34d399',
          backgroundColor: 'rgba(52,211,153,0.1)',
          fill: true,
          tension: 0.3,
          yAxisID: 'y',
        },
        {
          label: 'Build (s)',
          data: buildData,
          borderColor: '#818cf8',
          borderDash: [4, 4],
          tension: 0.3,
          yAxisID: 'y1',
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#94a3b8', font: { size: 11 } } } },
      scales: {
        x: { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { color: '#334155' } },
        y: { position: 'left', min: 0, max: 100, ticks: { color: '#34d399', callback: v => v + '%' }, grid: { color: '#334155' } },
        y1: { position: 'right', min: 0, ticks: { color: '#818cf8', callback: v => v + 's' }, grid: { drawOnChartArea: false } },
      },
    },
  });
}

function renderVerdicts(history) {
  const el = document.getElementById('verdictTimeline');
  if (!history.length) { el.innerHTML = '<div style="color:var(--muted)">No iterations yet</div>'; return; }
  el.innerHTML = history.slice().reverse().map(h => {
    const badge = h.verdict === 'PASS'
      ? '<span class="badge badge-pass">PASS</span>'
      : '<span class="badge badge-fail">NEEDS_WORK</span>';
    const time = `Build ${fmt(h.build_seconds)} · Eval ${fmt(h.eval_seconds)}`;
    const findings = h.findings_summary ? `<div class="findings">${esc(h.findings_summary)}</div>` : '';
    return `<div class="timeline-item">${badge} Iteration #${h.iteration} <span class="timeline-meta">${time}</span>${findings}</div>`;
  }).join('');
}

function renderFeatures(features) {
  window._features = features;
  const el = document.getElementById('featureList');
  if (!features.length) { el.innerHTML = '<div style="color:var(--muted)">No features yet</div>'; return; }
  const filtered = currentFilter === 'all' ? features
    : currentFilter === 'pass' ? features.filter(f => f.passes)
    : features.filter(f => !f.passes);
  el.innerHTML = filtered.map((f, i) => {
    const badge = f.passes
      ? '<span class="badge badge-pass">PASS</span>'
      : '<span class="badge badge-fail">TODO</span>';
    return `<div class="feature-item">${badge}<span>${esc(f.description || '(no description)')}</span></div>`;
  }).join('');
}

function renderGit(commits) {
  const el = document.getElementById('gitList');
  if (!commits.length) { el.innerHTML = '<div style="color:var(--muted)">No commits</div>'; return; }
  el.innerHTML = commits.map(c =>
    `<div class="git-item"><span class="git-hash">${c.hash}</span> ${esc(c.message)}<br><span class="git-date">${c.date}</span></div>`
  ).join('');
}

function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

async function refresh() {
  try {
    const [status, history, features, git] = await Promise.all([
      fetch('/api/status').then(r => r.json()),
      fetch('/api/history').then(r => r.json()),
      fetch('/api/features').then(r => r.json()),
      fetch('/api/git-log').then(r => r.json()),
    ]);
    renderStatus(status);
    renderTrend(history);
    renderVerdicts(history);
    renderFeatures(features);
    renderGit(git);
    document.getElementById('refreshNote').textContent = `Last updated: ${new Date().toLocaleTimeString()} · Auto-refresh: 5s`;
  } catch (e) {
    document.getElementById('refreshNote').textContent = `Error: ${e.message} · Retrying in 5s`;
  }
}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    project_dir: Path = Path(".")

    def do_GET(self):
        path = urlparse(self.path).path

        try:
            if path == "/" or path == "/index.html":
                self._html(DASHBOARD_HTML)
            elif path == "/api/status":
                self._json(read_status(self.project_dir) or {})
            elif path == "/api/history":
                self._json(read_history(self.project_dir))
            elif path == "/api/features":
                self._json(get_features(self.project_dir))
            elif path == "/api/git-log":
                self._json(get_git_log(self.project_dir))
            else:
                self.send_error(404)
        except Exception:
            self._json({"error": "internal server error"})

    def _json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description="Claude Harness Dashboard")
    parser.add_argument("project_dir", type=Path, help="Project directory to monitor")
    parser.add_argument("--port", type=int, default=8077, help="HTTP port (default: 8077)")
    args = parser.parse_args()

    project_dir = args.project_dir
    if not project_dir.is_absolute():
        project_dir = Path("generations") / project_dir
    project_dir = project_dir.resolve()

    if not project_dir.exists():
        print(f"Error: {project_dir} does not exist.")
        sys.exit(1)

    DashboardHandler.project_dir = project_dir

    server = HTTPServer(("0.0.0.0", args.port), DashboardHandler)
    print(f"Dashboard: http://localhost:{args.port}")
    print(f"Monitoring: {project_dir}")
    print("Press Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
