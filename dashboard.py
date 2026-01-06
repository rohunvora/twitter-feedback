#!/usr/bin/env python3
"""
Real-time Twitter Feedback Dashboard

Run: python dashboard.py
Opens at: http://localhost:8765
"""

import sqlite3
import json
import webbrowser
import threading
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

PROJECT_DIR = Path(__file__).parent.resolve()
DB_PATH = PROJECT_DIR / "data" / "feedback.db"

# Tweet URLs for linking
TWEET_IDS = [
    "2008652887136891376",
    "2008659908095533340",
]


def get_dashboard_data():
    """Get all data for the dashboard."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Get category counts
    categories = conn.execute("""
        SELECT a.category, COUNT(*) as count
        FROM analysis a
        JOIN tweets t ON a.tweet_id = t.id
        WHERE t.parent_tweet_id IN (?, ?)
        GROUP BY a.category
        ORDER BY count DESC
    """, TWEET_IDS).fetchall()

    # Get high priority items (priority >= 1)
    high_priority = conn.execute("""
        SELECT t.id, t.author_username, t.text, t.tweet_type, t.metrics, t.created_at,
               a.category, a.priority, t.parent_tweet_id
        FROM tweets t
        JOIN analysis a ON t.id = a.tweet_id
        WHERE t.parent_tweet_id IN (?, ?) AND a.priority >= 1
        ORDER BY a.priority DESC, CAST(t.id AS INTEGER) DESC
        LIMIT 50
    """, TWEET_IDS).fetchall()

    # Get recent tweets (all categories)
    recent = conn.execute("""
        SELECT t.id, t.author_username, t.text, t.tweet_type, t.metrics, t.created_at,
               a.category, a.priority, t.parent_tweet_id
        FROM tweets t
        JOIN analysis a ON t.id = a.tweet_id
        WHERE t.parent_tweet_id IN (?, ?)
        ORDER BY CAST(t.id AS INTEGER) DESC
        LIMIT 100
    """, TWEET_IDS).fetchall()

    # Total count
    total = conn.execute("""
        SELECT COUNT(*) FROM tweets WHERE parent_tweet_id IN (?, ?)
    """, TWEET_IDS).fetchone()[0]

    # Per-tweet breakdown
    per_tweet = conn.execute("""
        SELECT parent_tweet_id, COUNT(*) as count
        FROM tweets
        WHERE parent_tweet_id IN (?, ?)
        GROUP BY parent_tweet_id
    """, TWEET_IDS).fetchall()

    conn.close()

    return {
        "categories": [dict(r) for r in categories],
        "high_priority": [dict(r) for r in high_priority],
        "recent": [dict(r) for r in recent],
        "total": total,
        "per_tweet": [dict(r) for r in per_tweet],
        "last_updated": datetime.now().isoformat()
    }


def render_dashboard():
    """Render the HTML dashboard."""
    data = get_dashboard_data()

    # Category colors
    cat_colors = {
        "feature_request": "#22c55e",
        "question": "#3b82f6",
        "bug_report": "#ef4444",
        "praise": "#a855f7",
        "criticism": "#f97316",
        "joke": "#eab308",
        "spam": "#6b7280",
        "other": "#94a3b8"
    }

    # Build category stats HTML
    cat_html = ""
    for cat in data["categories"]:
        color = cat_colors.get(cat["category"], "#94a3b8")
        cat_html += f'''
        <div class="stat-card" style="border-left: 4px solid {color}">
            <div class="stat-value">{cat["count"]}</div>
            <div class="stat-label">{cat["category"].replace("_", " ").title()}</div>
        </div>'''

    # Build high priority items HTML
    priority_html = ""
    for item in data["high_priority"]:
        color = cat_colors.get(item["category"], "#94a3b8")
        text = item["text"].replace("<", "&lt;").replace(">", "&gt;")[:200]
        metrics = json.loads(item["metrics"]) if item["metrics"] else {}
        likes = metrics.get("like_count", 0)
        tweet_url = f"https://x.com/{item['author_username']}/status/{item['id']}"
        priority_html += f'''
        <div class="tweet-card priority-{item['priority']}">
            <div class="tweet-header">
                <a href="{tweet_url}" target="_blank" class="username">@{item["author_username"]}</a>
                <span class="tag" style="background: {color}">{item["category"].replace("_", " ")}</span>
                <span class="likes">❤️ {likes}</span>
            </div>
            <div class="tweet-text">{text}</div>
        </div>'''

    # Build recent tweets HTML
    recent_html = ""
    for item in data["recent"]:
        color = cat_colors.get(item["category"], "#94a3b8")
        text = item["text"].replace("<", "&lt;").replace(">", "&gt;")[:150]
        tweet_url = f"https://x.com/{item['author_username']}/status/{item['id']}"
        recent_html += f'''
        <div class="tweet-card mini">
            <div class="tweet-header">
                <a href="{tweet_url}" target="_blank" class="username">@{item["author_username"]}</a>
                <span class="tag" style="background: {color}">{item["category"].replace("_", " ")}</span>
            </div>
            <div class="tweet-text">{text}</div>
        </div>'''

    return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Twitter Feedback Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f0f0f;
            color: #e5e5e5;
            min-height: 100vh;
        }}
        .header {{
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            padding: 24px 32px;
            border-bottom: 1px solid #333;
            position: sticky;
            top: 0;
            z-index: 100;
        }}
        .header h1 {{
            font-size: 24px;
            font-weight: 600;
            margin-bottom: 8px;
        }}
        .header .meta {{
            color: #888;
            font-size: 14px;
        }}
        .header .meta a {{ color: #60a5fa; }}
        .refresh-indicator {{
            position: absolute;
            right: 32px;
            top: 50%;
            transform: translateY(-50%);
            display: flex;
            align-items: center;
            gap: 8px;
            color: #888;
            font-size: 12px;
        }}
        .refresh-indicator .dot {{
            width: 8px;
            height: 8px;
            background: #22c55e;
            border-radius: 50%;
            animation: pulse 2s infinite;
        }}
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.4; }}
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 24px;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 16px;
            margin-bottom: 32px;
        }}
        .stat-card {{
            background: #1a1a1a;
            border-radius: 8px;
            padding: 16px;
        }}
        .stat-value {{
            font-size: 32px;
            font-weight: 700;
            color: #fff;
        }}
        .stat-label {{
            font-size: 12px;
            color: #888;
            text-transform: uppercase;
            margin-top: 4px;
        }}
        .section {{
            margin-bottom: 32px;
        }}
        .section h2 {{
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 16px;
            color: #fff;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .section h2 .count {{
            background: #333;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 12px;
            color: #888;
        }}
        .tweets-grid {{
            display: grid;
            gap: 12px;
        }}
        .tweet-card {{
            background: #1a1a1a;
            border-radius: 8px;
            padding: 16px;
            border: 1px solid #262626;
            transition: border-color 0.2s;
        }}
        .tweet-card:hover {{
            border-color: #404040;
        }}
        .tweet-card.priority-2 {{
            border-left: 3px solid #ef4444;
        }}
        .tweet-card.priority-1 {{
            border-left: 3px solid #f97316;
        }}
        .tweet-card.mini {{
            padding: 12px;
        }}
        .tweet-header {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 8px;
            flex-wrap: wrap;
        }}
        .username {{
            font-weight: 600;
            color: #60a5fa;
            text-decoration: none;
        }}
        .username:hover {{ text-decoration: underline; }}
        .tag {{
            font-size: 10px;
            padding: 2px 8px;
            border-radius: 12px;
            color: #fff;
            text-transform: uppercase;
            font-weight: 500;
        }}
        .likes {{
            font-size: 12px;
            color: #888;
            margin-left: auto;
        }}
        .tweet-text {{
            font-size: 14px;
            line-height: 1.5;
            color: #ccc;
        }}
        .mini .tweet-text {{
            font-size: 13px;
        }}
        .columns {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
        }}
        @media (max-width: 900px) {{
            .columns {{ grid-template-columns: 1fr; }}
        }}
        .total-badge {{
            background: linear-gradient(135deg, #3b82f6, #8b5cf6);
            color: white;
            padding: 4px 12px;
            border-radius: 16px;
            font-size: 14px;
            font-weight: 600;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Twitter Feedback Dashboard <span class="total-badge">{data["total"]} responses</span></h1>
        <div class="meta">
            Tracking:
            <a href="https://x.com/frankdegods/status/2008652887136891376" target="_blank">Tweet 1</a> ·
            <a href="https://x.com/frankdegods/status/2008659908095533340" target="_blank">Tweet 2</a>
        </div>
        <div class="refresh-indicator">
            <div class="dot"></div>
            Auto-refresh 30s
        </div>
    </div>

    <div class="container">
        <div class="stats-grid">
            <div class="stat-card" style="border-left: 4px solid #fff">
                <div class="stat-value">{data["total"]}</div>
                <div class="stat-label">Total Responses</div>
            </div>
            {cat_html}
        </div>

        <div class="columns">
            <div class="section">
                <h2>🔥 High Priority <span class="count">{len(data["high_priority"])}</span></h2>
                <div class="tweets-grid">
                    {priority_html if priority_html else '<div style="color:#666">No high priority items</div>'}
                </div>
            </div>

            <div class="section">
                <h2>🕐 Recent Feedback <span class="count">{len(data["recent"])}</span></h2>
                <div class="tweets-grid">
                    {recent_html}
                </div>
            </div>
        </div>
    </div>

    <script>
        // Auto-refresh every 30 seconds
        setTimeout(() => location.reload(), 30000);
    </script>
</body>
</html>'''


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/" or path == "/dashboard":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(render_dashboard().encode())

        elif path == "/api/data":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(get_dashboard_data()).encode())

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress default logging


def main():
    port = 8765
    server = HTTPServer(("localhost", port), DashboardHandler)
    url = f"http://localhost:{port}"

    print(f"\n🚀 Dashboard running at: {url}")
    print("   Auto-refreshes every 30 seconds")
    print("   Press Ctrl+C to stop\n")

    # Open browser after short delay
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
