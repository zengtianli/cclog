"""Static HTML site generator for cclog."""

import json
from datetime import date, timedelta
from pathlib import Path
from string import Template

from cclog.config import Config
from cclog.digest import build_daily_digest, build_weekly_digest
from cclog.indexer import Indexer

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def generate_site(config: Config, output_dir: Path, api_mode: bool = False):
    """Generate the complete static site."""
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "sessions").mkdir(exist_ok=True)
    (output_dir / "digests").mkdir(exist_ok=True)

    indexer = Indexer(config)

    # Get all sessions
    sessions = indexer.list_sessions(limit=10000)
    stats = indexer.get_stats()

    # Generate pages
    _generate_index(sessions, stats, output_dir, api_mode=api_mode)
    _generate_session_pages(sessions, output_dir)
    _generate_digest_pages(indexer, sessions, config, output_dir)

    # Copy CSS
    css_src = _TEMPLATES_DIR / "style.css"
    (output_dir / "style.css").write_text(css_src.read_text(encoding="utf-8"), encoding="utf-8")

    indexer.close()

    print(f"Site generated: {output_dir}")
    print(f"  {len(sessions)} session pages")
    print(f"  Index + digests")


def _generate_index(sessions: list, stats: dict, output_dir: Path, api_mode: bool = False):
    """Generate the main index.html dashboard."""
    # Build session data for JS filtering
    session_data = []
    for s in sessions:
        session_data.append({
            "id": s.session_id,
            "project": s.project,
            "date": s.start_time.strftime("%Y-%m-%d") if s.start_time else "",
            "time": s.start_time.strftime("%H:%M") if s.start_time else "",
            "duration": s.duration_minutes,
            "msgs": s.message_count,
            "category": s.category or "",
            "summary": s.summary or "",
            "title": s.title or "",
            "model": s.model or "",
            "has_summary": bool(s.summary),
            "outcomes": s.outcomes or "",
            "learnings": s.learnings or [],
        })

    # Collect unique projects and categories
    projects = sorted(set(s["project"] for s in session_data if s["project"]))
    categories = sorted(set(s["category"] for s in session_data if s["category"]))

    total_hours = (stats.get("total_minutes") or 0) / 60

    # Project options HTML
    project_options = "\n".join(f'        <option value="{p}">{p}</option>' for p in projects)
    category_options = "\n".join(f'        <option value="{c}">{c}</option>' for c in categories)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>cclog - Session Dashboard</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header>
    <div class="container">
      <h1>cclog</h1>
      <p class="subtitle">Claude Code Session Dashboard</p>
      <nav>
        <a href="index.html" class="active">Sessions</a>
        <a href="digests/index.html">Digests</a>
      </nav>
    </div>
  </header>

  <main class="container">
    <div class="stats">
      <div class="stat-card">
        <div class="label">Sessions</div>
        <div class="value">{stats.get('total_sessions', 0)}</div>
      </div>
      <div class="stat-card">
        <div class="label">Projects</div>
        <div class="value">{stats.get('total_projects', 0)}</div>
      </div>
      <div class="stat-card">
        <div class="label">Total Hours</div>
        <div class="value">{total_hours:.0f}</div>
      </div>
      <div class="stat-card">
        <div class="label">Summarized</div>
        <div class="value">{stats.get('summarized_sessions', 0)}</div>
      </div>
    </div>

    <div class="filters">
      <input type="date" id="filterDate" placeholder="Date">
      <select id="filterProject">
        <option value="">All Projects</option>
{project_options}
      </select>
      <select id="filterCategory">
        <option value="">All Categories</option>
{category_options}
      </select>
      <input type="text" id="filterSearch" placeholder="Search...">
    </div>

    <table class="session-table">
      <thead>
        <tr>
          <th class="sortable" data-sort="date">Date<span class="sort-arrow"> &#9660;</span></th>
          <th>Project</th>
          <th class="sortable duration" data-sort="duration">Duration<span class="sort-arrow"></span></th>
          <th class="sortable msgs" data-sort="msgs">Msgs<span class="sort-arrow"></span></th>
          <th>Category</th>
          <th>Summary</th>
          {'<th class="actions"><input type="checkbox" id="selectAll" title="全选"></th>' if api_mode else ''}
        </tr>
      </thead>
      <tbody id="sessionBody"></tbody>
    </table>
    {'<div class="bulk-bar" id="bulkBar" style="display:none"><span id="selectedCount">0</span> 个已选 <button class="btn-bulk-delete" id="bulkDeleteBtn">批量删除</button></div>' if api_mode else ''}
  </main>

  <footer>
    <div class="container">
      Generated by <a href="https://github.com/zengtianli/cclog">cclog</a>
    </div>
  </footer>

  <script>
    let sessions = {'[]' if api_mode else json.dumps(session_data, ensure_ascii=False)};
    const API_MODE = {'true' if api_mode else 'false'};
    let sortState = {{ key: 'date', dir: 'desc' }};
    let currentFiltered = sessions;

    function updateStats() {{
      const cards = document.querySelectorAll('.stat-card .value');
      cards[0].textContent = sessions.length;
      cards[1].textContent = new Set(sessions.map(s => s.project)).size;
      cards[2].textContent = Math.round(sessions.reduce((a, s) => a + (s.duration || 0), 0) / 60);
      cards[3].textContent = sessions.filter(s => s.has_summary).length;
    }}

    // API mode: load sessions from external JSON file
    if (API_MODE) {{
      fetch('sessions.json').then(r => r.json()).then(data => {{
        sessions = data;
        currentFiltered = sessions;
        applyFilters();
        updateSortHeaders();
        updateStats();
      }});
    }}

    const CAT_CLASS = {{
      'development': 'tag-dev', 'configuration': 'tag-config',
      'debugging': 'tag-debug', 'writing': 'tag-writing',
      'analysis': 'tag-analysis', 'learning': 'tag-learning',
      'organization': 'tag-org', 'discussion': 'tag-dev'
    }};

    function esc(s) {{
      return s ? s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;') : '';
    }}

    function sortData(data) {{
      const {{ key, dir }} = sortState;
      return [...data].sort((a, b) => {{
        let va, vb;
        if (key === 'date') {{ va = a.date + a.time; vb = b.date + b.time; }}
        else {{ va = a[key] || 0; vb = b[key] || 0; }}
        if (typeof va === 'number') return dir === 'asc' ? va - vb : vb - va;
        return dir === 'asc' ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
      }});
    }}

    function updateSortHeaders() {{
      document.querySelectorAll('th.sortable').forEach(th => {{
        const arrow = th.querySelector('.sort-arrow');
        if (th.dataset.sort === sortState.key) {{
          arrow.innerHTML = sortState.dir === 'asc' ? ' &#9650;' : ' &#9660;';
        }} else {{
          arrow.textContent = '';
        }}
      }});
    }}

    function render(filtered) {{
      currentFiltered = filtered;
      const sorted = sortData(filtered);
      const body = document.getElementById('sessionBody');
      body.innerHTML = sorted.map((s, i) => {{
        let summaryCell, catCell;
        if (s.has_summary) {{
          const trunc = s.summary.length > 80 ? s.summary.slice(0, 77) + '...' : s.summary;
          summaryCell = `<span title="${{esc(s.summary)}}">${{esc(trunc)}}</span>`;
          catCell = s.category ? `<span class="tag ${{CAT_CLASS[s.category] || 'tag-dev'}}">${{s.category}}</span>` : '';
        }} else {{
          const t = s.title || '-';
          const trunc = t.length > 50 ? t.slice(0, 47) + '...' : t;
          summaryCell = `<span class="tag tag-unsummarized">未摘要</span> <span class="unsummarized">${{esc(trunc)}}</span>`;
          catCell = '';
        }}

        // Delete recommendation
        let recTag = '';
        if (API_MODE) {{
          if (s.has_summary && s.learnings && s.learnings.length) {{
            recTag = '<span class="tag tag-deletable" title="摘要+经验已提取，可安全删除">可删</span> ';
          }} else if (s.msgs < 5) {{
            recTag = '<span class="tag tag-low" title="消息过少，低价值">低价值</span> ';
          }}
          summaryCell = recTag + summaryCell;
        }}

        let expandRow = '';
        if (s.has_summary) {{
          let ec = `<h4>Summary</h4><p>${{esc(s.summary)}}</p>`;
          if (s.outcomes) ec += `<h4>Outcomes</h4><p>${{esc(s.outcomes)}}</p>`;
          if (s.learnings && s.learnings.length) {{
            ec += `<h4>Learnings</h4><ul>${{s.learnings.map(l => '<li>' + esc(l) + '</li>').join('')}}</ul>`;
          }}
          expandRow = `<tr class="expand-row" id="expand-${{i}}" style="display:none"><td colspan="${{API_MODE ? 7 : 6}}"><div class="expand-content">${{ec}}</div></td></tr>`;
        }}

        const actionsCell = API_MODE ? `<td class="actions"><input type="checkbox" class="row-select" data-id="${{s.id}}"></td>` : '';

        return `<tr class="${{s.has_summary ? 'expandable' : ''}}" data-expand="${{i}}">
          <td><a href="sessions/${{s.id}}.html">${{s.date}} ${{s.time}}</a></td>
          <td class="project">${{s.project}}</td>
          <td class="duration">${{s.duration}}m</td>
          <td class="msgs">${{s.msgs}}</td>
          <td>${{catCell}}</td>
          <td>${{summaryCell}}</td>
          ${{actionsCell}}
        </tr>${{expandRow}}`;
      }}).join('');
    }}

    function applyFilters() {{
      let f = sessions;
      const d = document.getElementById('filterDate').value;
      const p = document.getElementById('filterProject').value;
      const c = document.getElementById('filterCategory').value;
      const q = document.getElementById('filterSearch').value.toLowerCase();
      if (d) f = f.filter(s => s.date === d);
      if (p) f = f.filter(s => s.project === p);
      if (c) f = f.filter(s => s.category === c);
      if (q) f = f.filter(s =>
        (s.summary + s.title + s.project).toLowerCase().includes(q)
      );
      render(f);
      updateSortHeaders();
    }}

    // Sort click handlers
    document.querySelectorAll('th.sortable').forEach(th => {{
      th.addEventListener('click', () => {{
        const key = th.dataset.sort;
        if (sortState.key === key) {{
          sortState.dir = sortState.dir === 'asc' ? 'desc' : 'asc';
        }} else {{
          sortState = {{ key, dir: key === 'date' ? 'desc' : 'desc' }};
        }}
        render(currentFiltered);
        updateSortHeaders();
      }});
    }});

    // Expand row click handler (event delegation)
    document.getElementById('sessionBody').addEventListener('click', (e) => {{
      const row = e.target.closest('tr.expandable');
      if (!row || e.target.closest('a')) return;
      const idx = row.dataset.expand;
      const expandRow = document.getElementById('expand-' + idx);
      if (expandRow) {{
        expandRow.style.display = expandRow.style.display === 'none' ? '' : 'none';
        row.classList.toggle('expanded');
      }}
    }});

    document.getElementById('filterDate').addEventListener('change', applyFilters);
    document.getElementById('filterProject').addEventListener('change', applyFilters);
    document.getElementById('filterCategory').addEventListener('change', applyFilters);
    document.getElementById('filterSearch').addEventListener('input', applyFilters);

    function updateBulkBar() {{
      const checked = document.querySelectorAll('.row-select:checked');
      const bar = document.getElementById('bulkBar');
      if (!bar) return;
      if (checked.length > 0) {{
        bar.style.display = 'flex';
        document.getElementById('selectedCount').textContent = checked.length;
      }} else {{
        bar.style.display = 'none';
      }}
    }}

    async function deleteIds(ids) {{
      let ok = 0;
      for (const id of ids) {{
        try {{
          const r = await fetch('/api/delete', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ session_id: id }})
          }});
          const data = await r.json();
          if (data.deleted) {{
            const idx = sessions.findIndex(s => s.id === id);
            if (idx !== -1) sessions.splice(idx, 1);
            ok++;
          }}
        }} catch(e) {{}}
      }}
      return ok;
    }}

    if (API_MODE) {{
      // Select all checkbox
      document.getElementById('selectAll').addEventListener('change', (e) => {{
        document.querySelectorAll('.row-select').forEach(cb => cb.checked = e.target.checked);
        updateBulkBar();
      }});

      // Individual checkbox change (event delegation)
      document.getElementById('sessionBody').addEventListener('change', (e) => {{
        if (e.target.classList.contains('row-select')) updateBulkBar();
      }});

      // Bulk delete button
      document.getElementById('bulkDeleteBtn').addEventListener('click', async () => {{
        const checked = document.querySelectorAll('.row-select:checked');
        const ids = Array.from(checked).map(cb => cb.dataset.id);
        if (!ids.length) return;
        if (!confirm(`确定删除 ${{ids.length}} 个会话？`)) return;
        const btn = document.getElementById('bulkDeleteBtn');
        btn.disabled = true;
        btn.textContent = '删除中...';
        const ok = await deleteIds(ids);
        btn.disabled = false;
        btn.textContent = '批量删除';
        document.getElementById('selectAll').checked = false;
        applyFilters();
        updateBulkBar();
        updateStats();
      }});
    }}

    render(sessions);
    updateSortHeaders();
  </script>
</body>
</html>"""

    (output_dir / "index.html").write_text(html, encoding="utf-8")

    # API mode: write sessions data as separate JSON file
    if api_mode:
        (output_dir / "sessions.json").write_text(
            json.dumps(session_data, ensure_ascii=False), encoding="utf-8"
        )


def _generate_session_pages(sessions: list, output_dir: Path):
    """Generate individual session detail pages."""
    for s in sessions:
        tools_html = ", ".join(s.tools_used) if s.tools_used else "-"
        files_html = ""
        if s.files_modified:
            items = "\n".join(f"    <li>{f}</li>" for f in s.files_modified[:20])
            files_html = f'<div class="summary-box"><h3>Files Modified ({len(s.files_modified)})</h3><ul>{items}</ul></div>'

        summary_html = ""
        if s.summary:
            learnings_html = ""
            if s.learnings:
                items = "\n".join(f"<li>{l}</li>" for l in s.learnings)
                learnings_html = f"<h3>Learnings</h3><ul>{items}</ul>"

            summary_html = f"""<div class="summary-box">
      <h3>Summary</h3><p>{_esc(s.summary)}</p>
      {f'<h3>Outcomes</h3><p>{_esc(s.outcomes)}</p>' if s.outcomes else ''}
      {learnings_html}
    </div>"""

        cat_class = {
            "development": "tag-dev", "configuration": "tag-config",
            "debugging": "tag-debug", "writing": "tag-writing",
            "analysis": "tag-analysis", "learning": "tag-learning",
            "organization": "tag-org", "discussion": "tag-dev",
        }.get(s.category or "", "tag-dev")

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{_esc(s.project)} - {_esc(s.start_time.strftime('%Y-%m-%d %H:%M') if s.start_time else '')}</title>
  <link rel="stylesheet" href="../style.css">
</head>
<body>
  <header>
    <div class="container">
      <h1>cclog</h1>
      <nav>
        <a href="../index.html">Sessions</a>
        <a href="../digests/index.html">Digests</a>
      </nav>
    </div>
  </header>
  <main class="container session-detail">
    <h2>{_esc(s.project)} {s.category and f'<span class="tag {cat_class}">{s.category}</span>' or ''}</h2>
    <div class="meta-grid">
      <span class="key">Session ID</span><span class="val">{s.session_id}</span>
      <span class="key">Slug</span><span class="val">{s.slug or '-'}</span>
      <span class="key">Date</span><span class="val">{s.start_time.strftime('%Y-%m-%d %H:%M') if s.start_time else '-'}</span>
      <span class="key">Duration</span><span class="val">{s.duration_minutes} min</span>
      <span class="key">Messages</span><span class="val">{s.message_count} ({s.user_message_count} user)</span>
      <span class="key">Model</span><span class="val">{s.model or '-'}</span>
      <span class="key">Branch</span><span class="val">{s.git_branch or '-'}</span>
      <span class="key">Tokens</span><span class="val">{s.tokens.input_tokens:,} in / {s.tokens.output_tokens:,} out</span>
      <span class="key">Tools</span><span class="val">{tools_html}</span>
    </div>
    {summary_html}
    {files_html}
  </main>
  <footer><div class="container">Generated by <a href="https://github.com/zengtianli/cclog">cclog</a></div></footer>
</body>
</html>"""

        (output_dir / "sessions" / f"{s.session_id}.html").write_text(html, encoding="utf-8")


def _generate_digest_pages(indexer: Indexer, sessions: list, config: Config, output_dir: Path):
    """Generate digest index and per-date pages."""
    # Collect all dates that have sessions
    dates_set: set[str] = set()
    for s in sessions:
        if s.start_time:
            dates_set.add(s.start_time.strftime("%Y-%m-%d"))

    dates = sorted(dates_set, reverse=True)

    # Generate digest index
    date_links = "\n".join(
        f'    <li><a href="{d}.html">{d}</a></li>' for d in dates[:60]
    )

    digest_index = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>cclog - Digests</title>
  <link rel="stylesheet" href="../style.css">
</head>
<body>
  <header>
    <div class="container">
      <h1>cclog</h1>
      <nav>
        <a href="../index.html">Sessions</a>
        <a href="index.html" class="active">Digests</a>
      </nav>
    </div>
  </header>
  <main class="container">
    <h2>Daily Digests</h2>
    <ul style="list-style:none; padding:0; margin:16px 0;">
{date_links}
    </ul>
  </main>
  <footer><div class="container">Generated by <a href="https://github.com/zengtianli/cclog">cclog</a></div></footer>
</body>
</html>"""

    (output_dir / "digests" / "index.html").write_text(digest_index, encoding="utf-8")

    # Generate per-date pages
    for d_str in dates[:60]:
        d = date.fromisoformat(d_str)
        digest = build_daily_digest(indexer, d, config.timezone)

        sessions_html = ""
        for s in digest.sessions:
            time_str = s.start_time.strftime("%H:%M") if s.start_time else "?"
            desc = s.summary or s.title or "-"

            sessions_html += f"""<div class="digest-session">
        <h3><a href="../sessions/{s.session_id}.html">{s.project}</a></h3>
        <span class="time">{time_str} - {s.duration_minutes}m</span>
        <p>{_esc(desc)}</p>
      </div>\n"""

        tokens = digest.total_tokens
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>cclog - {d_str}</title>
  <link rel="stylesheet" href="../style.css">
</head>
<body>
  <header>
    <div class="container">
      <h1>cclog</h1>
      <nav>
        <a href="../index.html">Sessions</a>
        <a href="index.html" class="active">Digests</a>
      </nav>
    </div>
  </header>
  <main class="container">
    <h2>{d_str} Daily Digest</h2>
    <div class="stats">
      <div class="stat-card"><div class="label">Sessions</div><div class="value">{len(digest.sessions)}</div></div>
      <div class="stat-card"><div class="label">Duration</div><div class="value">{digest.total_duration_minutes}m</div></div>
      <div class="stat-card"><div class="label">Projects</div><div class="value">{len(digest.projects_touched)}</div></div>
      <div class="stat-card"><div class="label">Tokens</div><div class="value">{tokens.total:,}</div></div>
    </div>
    {sessions_html}
  </main>
  <footer><div class="container">Generated by <a href="https://github.com/zengtianli/cclog">cclog</a></div></footer>
</body>
</html>"""

        (output_dir / "digests" / f"{d_str}.html").write_text(html, encoding="utf-8")


def _esc(text: str | None) -> str:
    """Escape HTML special characters."""
    if not text:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
