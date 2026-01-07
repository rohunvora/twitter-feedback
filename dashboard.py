#!/usr/bin/env python3
"""
Twitter Feedback Dashboard - v2
Star/Archive/Spam triage with snappy sorting and filters

Run: python dashboard.py
Opens at: http://localhost:8765
"""

import sqlite3
import json
import webbrowser
import threading
import subprocess
import re
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

PROJECT_DIR = Path(__file__).parent.resolve()
DB_PATH = PROJECT_DIR / "data" / "feedback.db"


def get_tracked_tweets():
    """Get list of parent tweet IDs being tracked."""
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    result = conn.execute("SELECT DISTINCT parent_tweet_id FROM tweets").fetchall()
    conn.close()
    return [r[0] for r in result]


def get_dashboard_data():
    """Get all data for the dashboard."""
    tweet_ids = get_tracked_tweets()
    if not tweet_ids:
        return {"items": [], "total": 0, "tracked_tweets": [], "last_updated": datetime.now().isoformat()}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    placeholders = ",".join("?" * len(tweet_ids))

    all_items = conn.execute(f"""
        SELECT t.id, t.author_username, t.text, t.tweet_type, t.metrics, t.created_at,
               COALESCE(a.category, 'other') as category, COALESCE(a.priority, 0) as priority, t.parent_tweet_id
        FROM tweets t
        LEFT JOIN analysis a ON t.id = a.tweet_id
        WHERE t.parent_tweet_id IN ({placeholders})
        ORDER BY CAST(t.id AS INTEGER) DESC
    """, tweet_ids).fetchall()

    total = conn.execute(f"""
        SELECT COUNT(*) FROM tweets WHERE parent_tweet_id IN ({placeholders})
    """, tweet_ids).fetchone()[0]

    conn.close()

    return {
        "items": [dict(r) for r in all_items],
        "total": total,
        "tracked_tweets": tweet_ids,
        "last_updated": datetime.now().isoformat()
    }


def render_dashboard():
    """Render the HTML dashboard."""
    data = get_dashboard_data()

    # Build items HTML with data attributes for sorting
    items_html = ""
    for item in data["items"]:
        text_raw = item["text"].replace("<", "&lt;").replace(">", "&gt;")
        text_preview = text_raw[:140] + "..." if len(text_raw) > 140 else text_raw
        text_escaped = text_raw.replace("'", "\\'").replace('"', '\\"').replace('\n', ' ')
        metrics = json.loads(item["metrics"]) if item["metrics"] else {}
        likes = metrics.get("like_count", 0)
        tweet_url = f"https://x.com/{item['author_username']}/status/{item['id']}"
        priority = item.get("priority", 0)
        # Use tweet ID as timestamp proxy (Twitter IDs are time-ordered)
        timestamp = item['id']

        items_html += f'''
        <div class="item" data-id="{item['id']}" data-username="{item['author_username']}"
             data-text="{text_escaped}" data-priority="{priority}" data-timestamp="{timestamp}" data-likes="{likes}">
            <div class="item-content">
                <div class="item-header">
                    <a href="{tweet_url}" target="_blank" class="username">@{item["author_username"]}</a>
                    {f'<span class="likes">♥ {likes}</span>' if likes > 0 else ''}
                </div>
                <div class="item-text">{text_preview}</div>
                <div class="item-note" id="note-{item['id']}"></div>
            </div>
            <div class="item-actions">
                <button class="action-btn star" onclick="starItem('{item['id']}')" title="Star">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg>
                </button>
                <button class="action-btn archive" onclick="archiveItem('{item['id']}')" title="Archive">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="21 8 21 21 3 21 3 8"></polyline><rect x="1" y="3" width="22" height="5"></rect><line x1="10" y1="12" x2="14" y2="12"></line></svg>
                </button>
                <button class="action-btn spam" onclick="spamItem('{item['id']}')" title="Spam/Irrelevant">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                </button>
                <button class="action-btn note" onclick="toggleNote('{item['id']}')" title="Add note">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                </button>
            </div>
            <div class="note-input" id="note-input-{item['id']}">
                <input type="text" placeholder="Add a note..." onkeydown="saveNote('{item['id']}', event)">
            </div>
        </div>'''

    return f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Feedback Inbox</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f8fafc;
            color: #1e293b;
            min-height: 100vh;
        }}

        .container {{
            max-width: 900px;
            margin: 0 auto;
            padding: 24px;
        }}

        /* Header */
        .header {{
            margin-bottom: 20px;
        }}

        .header h1 {{
            font-size: 24px;
            font-weight: 600;
            margin-bottom: 8px;
        }}

        .header-meta {{
            display: flex;
            align-items: center;
            gap: 16px;
            color: #64748b;
            font-size: 14px;
        }}

        /* Sort controls */
        .sort-bar {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 16px;
            padding: 12px 16px;
            background: #fff;
            border-radius: 8px;
            border: 1px solid #e2e8f0;
        }}

        .sort-label {{
            font-size: 13px;
            color: #64748b;
            margin-right: 4px;
        }}

        .sort-btn {{
            padding: 6px 12px;
            border: 1px solid #e2e8f0;
            background: #fff;
            border-radius: 6px;
            font-size: 13px;
            cursor: pointer;
            transition: all 0.15s;
        }}

        .sort-btn:hover {{
            background: #f1f5f9;
        }}

        .sort-btn.active {{
            background: #1e293b;
            color: #fff;
            border-color: #1e293b;
        }}

        .sort-btn .arrow {{
            margin-left: 4px;
            font-size: 10px;
        }}

        /* Filter chips */
        .filter-bar {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 16px;
        }}

        .filter-chip {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 6px 12px;
            border: 1px solid #e2e8f0;
            background: #fff;
            border-radius: 16px;
            font-size: 13px;
            cursor: pointer;
            transition: all 0.15s;
        }}

        .filter-chip:hover {{
            background: #f1f5f9;
        }}

        .filter-chip.active {{
            background: var(--chip-color, #1e293b);
            color: #fff;
            border-color: var(--chip-color, #1e293b);
        }}

        .filter-chip .chip-count {{
            background: rgba(0,0,0,0.1);
            padding: 2px 6px;
            border-radius: 10px;
            font-size: 11px;
        }}

        .filter-chip.active .chip-count {{
            background: rgba(255,255,255,0.2);
        }}

        .filter-divider {{
            width: 1px;
            height: 24px;
            background: #e2e8f0;
            margin: 0 4px;
        }}

        /* Status chips */
        .status-chip {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 6px 12px;
            border: 1px solid #e2e8f0;
            background: #fff;
            border-radius: 16px;
            font-size: 13px;
            cursor: pointer;
            transition: all 0.15s;
        }}

        .status-chip:hover {{
            background: #f1f5f9;
        }}

        .status-chip.active {{
            background: #1e293b;
            color: #fff;
            border-color: #1e293b;
        }}

        /* Items */
        .items-container {{
            background: #fff;
            border-radius: 12px;
            border: 1px solid #e2e8f0;
            overflow: hidden;
        }}

        .item {{
            display: flex;
            align-items: flex-start;
            gap: 12px;
            padding: 16px;
            border-bottom: 1px solid #f1f5f9;
            transition: background 0.15s;
            position: relative;
        }}

        .item:last-child {{
            border-bottom: none;
        }}

        .item:hover {{
            background: #f8fafc;
        }}

        .item.starred {{
            background: #fefce8;
        }}

        .item.starred:hover {{
            background: #fef9c3;
        }}

        .item.archived {{
            opacity: 0.5;
            display: none;
        }}

        .item.spammed {{
            opacity: 0.3;
            display: none;
        }}

        .item.hidden {{
            display: none;
        }}

        /* Show archived/spam based on filter */
        .show-archived .item.archived {{
            display: flex;
            opacity: 0.7;
        }}

        .show-spam .item.spammed {{
            display: flex;
            opacity: 0.5;
        }}

        .item-left {{
            flex-shrink: 0;
        }}

        .tag {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            color: #fff;
            text-transform: uppercase;
        }}

        .item-content {{
            flex: 1;
            min-width: 0;
        }}

        .item-header {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 4px;
        }}

        .username {{
            font-weight: 600;
            color: #1e293b;
            text-decoration: none;
        }}

        .username:hover {{
            text-decoration: underline;
        }}

        .likes {{
            font-size: 12px;
            color: #ef4444;
        }}

        .item-text {{
            color: #475569;
            font-size: 14px;
            line-height: 1.5;
        }}

        .item-note {{
            display: none;
            margin-top: 8px;
            padding: 8px 12px;
            background: #fef3c7;
            border-radius: 6px;
            font-size: 13px;
            color: #92400e;
        }}

        .item-note.visible {{
            display: block;
        }}

        /* Actions */
        .item-actions {{
            display: flex;
            gap: 4px;
            opacity: 0;
            transition: opacity 0.15s;
        }}

        .item:hover .item-actions {{
            opacity: 1;
        }}

        .action-btn {{
            width: 32px;
            height: 32px;
            border: none;
            background: #f1f5f9;
            border-radius: 6px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #64748b;
            transition: all 0.15s;
        }}

        .action-btn:hover {{
            background: #e2e8f0;
            color: #1e293b;
        }}

        .action-btn.star:hover {{
            background: #fef3c7;
            color: #f59e0b;
        }}

        .action-btn.archive:hover {{
            background: #dbeafe;
            color: #3b82f6;
        }}

        .action-btn.spam:hover {{
            background: #fee2e2;
            color: #ef4444;
        }}

        .item.starred .action-btn.star {{
            background: #fef3c7;
            color: #f59e0b;
        }}

        .item.starred .action-btn.star svg {{
            fill: #f59e0b;
        }}

        /* Note input */
        .note-input {{
            display: none;
            padding: 12px 16px;
            background: #f8fafc;
            border-top: 1px solid #e2e8f0;
            margin: 12px -16px -16px -16px;
        }}

        .note-input.visible {{
            display: block;
        }}

        .note-input input {{
            width: 100%;
            padding: 10px 12px;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            font-size: 14px;
            outline: none;
        }}

        .note-input input:focus {{
            border-color: #3b82f6;
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
        }}

        /* Stats bar */
        .stats-bar {{
            display: flex;
            gap: 16px;
            padding: 12px 16px;
            background: #fff;
            border-radius: 8px;
            border: 1px solid #e2e8f0;
            margin-bottom: 16px;
            font-size: 14px;
        }}

        .stat {{
            display: flex;
            align-items: center;
            gap: 6px;
        }}

        .stat-value {{
            font-weight: 600;
        }}

        .stat-label {{
            color: #64748b;
        }}

        /* Toast */
        .toast {{
            position: fixed;
            bottom: 24px;
            left: 50%;
            transform: translateX(-50%) translateY(100px);
            background: #1e293b;
            color: #fff;
            padding: 12px 24px;
            border-radius: 8px;
            font-size: 14px;
            opacity: 0;
            transition: all 0.3s;
            z-index: 1000;
        }}

        .toast.visible {{
            transform: translateX(-50%) translateY(0);
            opacity: 1;
        }}

        /* Copy button */
        .copy-btn {{
            padding: 8px 16px;
            background: #1e293b;
            color: #fff;
            border: none;
            border-radius: 6px;
            font-size: 13px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 6px;
        }}

        .copy-btn:hover {{
            background: #334155;
        }}

        /* Empty state */
        .empty-state {{
            padding: 48px;
            text-align: center;
            color: #64748b;
        }}

        .empty-state h3 {{
            font-size: 18px;
            margin-bottom: 8px;
            color: #1e293b;
        }}

        /* Add tweet bar */
        .add-tweet-bar {{
            display: flex;
            gap: 8px;
            margin-bottom: 16px;
            padding: 12px 16px;
            background: #fff;
            border-radius: 8px;
            border: 1px solid #e2e8f0;
        }}

        .add-tweet-bar input {{
            flex: 1;
            padding: 10px 14px;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            font-size: 14px;
            outline: none;
        }}

        .add-tweet-bar input:focus {{
            border-color: #3b82f6;
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
        }}

        .add-btn {{
            padding: 10px 20px;
            background: #10b981;
            color: #fff;
            border: none;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 6px;
            transition: background 0.15s;
        }}

        .add-btn:hover {{
            background: #059669;
        }}

        .add-btn:disabled {{
            background: #94a3b8;
            cursor: not-allowed;
        }}

        .add-btn.loading {{
            background: #94a3b8;
        }}

        .refresh-btn {{
            padding: 10px 20px;
            background: #3b82f6;
            color: #fff;
            border: none;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 6px;
            transition: background 0.15s;
        }}

        .refresh-btn:hover {{
            background: #2563eb;
        }}

        .refresh-btn:disabled {{
            background: #94a3b8;
            cursor: not-allowed;
        }}

        .refresh-btn svg.spinning {{
            animation: spin 1s linear infinite;
        }}

        @keyframes spin {{
            from {{ transform: rotate(0deg); }}
            to {{ transform: rotate(360deg); }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Feedback Inbox</h1>
            <div class="header-meta">
                <span>{data['total']} total items</span>
                <span>•</span>
                <span id="visible-count">{data['total']} showing</span>
                <span>•</span>
                <span>{len(data.get('tracked_tweets', []))} tweets tracked</span>
            </div>
        </div>

        <div class="add-tweet-bar">
            <input type="text" id="tweet-url-input" placeholder="Paste tweet URL to track (e.g. https://x.com/user/status/123...)" />
            <button class="add-btn" onclick="addTweet()" id="add-btn">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
                Add Tweet
            </button>
            <button class="refresh-btn" onclick="refreshAll()" id="refresh-btn">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg>
                Refresh
            </button>
        </div>

        <div class="stats-bar">
            <div class="stat">
                <span class="stat-value" id="inbox-count">{data['total']}</span>
                <span class="stat-label">Inbox</span>
            </div>
            <div class="stat">
                <span class="stat-value" id="starred-count">0</span>
                <span class="stat-label">Starred</span>
            </div>
            <div class="stat">
                <span class="stat-value" id="archived-count">0</span>
                <span class="stat-label">Archived</span>
            </div>
            <div class="stat">
                <span class="stat-value" id="spam-count">0</span>
                <span class="stat-label">Spam</span>
            </div>
            <div style="flex:1"></div>
            <button class="copy-btn" onclick="copyVisible()">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                Copy All
            </button>
        </div>

        <div class="sort-bar">
            <span class="sort-label">Sort:</span>
            <button class="sort-btn active" data-sort="time" onclick="setSort('time')">Recent <span class="arrow">↓</span></button>
            <button class="sort-btn" data-sort="priority" onclick="setSort('priority')">Priority</button>
            <button class="sort-btn" data-sort="likes" onclick="setSort('likes')">Likes</button>
        </div>

        <div class="filter-bar">
            <button class="status-chip active" data-status="inbox" onclick="setStatus('inbox')">Inbox</button>
            <button class="status-chip" data-status="starred" onclick="setStatus('starred')">⭐ Starred</button>
            <button class="status-chip" data-status="archived" onclick="setStatus('archived')">Archived</button>
            <button class="status-chip" data-status="spam" onclick="setStatus('spam')">Spam</button>
            <button class="status-chip" data-status="notes" onclick="setStatus('notes')">📝 With Notes</button>
        </div>

        <div class="items-container" id="items-container">
            {items_html}
            <div class="empty-state" id="empty-state" style="display:none">
                <h3>No items match your filters</h3>
                <p>Try adjusting your filters or sort options</p>
            </div>
        </div>
    </div>

    <div class="toast" id="toast"></div>

    <script>
        // State
        const starredItems = JSON.parse(localStorage.getItem('starredTweets') || '{{}}');
        const archivedItems = JSON.parse(localStorage.getItem('archivedTweets') || '{{}}');
        const spamItems = JSON.parse(localStorage.getItem('spamTweets') || '{{}}');
        const tweetNotes = JSON.parse(localStorage.getItem('tweetNotes') || '{{}}');

        let currentSort = 'time';
        let currentStatus = 'inbox';

        function init() {{
            // Apply saved state
            document.querySelectorAll('.item').forEach(item => {{
                const id = item.dataset.id;
                if (starredItems[id]) {{
                    item.classList.add('starred');
                }}
                if (archivedItems[id]) {{
                    item.classList.add('archived');
                }}
                if (spamItems[id]) {{
                    item.classList.add('spammed');
                }}
                if (tweetNotes[id]) {{
                    const noteEl = document.getElementById(`note-${{id}}`);
                    if (noteEl) {{
                        noteEl.textContent = '📝 ' + tweetNotes[id];
                        noteEl.classList.add('visible');
                    }}
                    item.dataset.hasNote = 'true';
                }}
            }});
            updateCounts();
            applyFilters();
        }}

        function starItem(id) {{
            const item = document.querySelector(`.item[data-id="${{id}}"]`);
            if (starredItems[id]) {{
                // Unstar
                delete starredItems[id];
                item.classList.remove('starred');
                showToast('Removed star');
            }} else {{
                // Star
                starredItems[id] = {{
                    username: item.dataset.username,
                    text: item.dataset.text,
                    category: item.dataset.category,
                    note: tweetNotes[id] || ''
                }};
                // Remove from archive/spam if exists
                delete archivedItems[id];
                delete spamItems[id];
                item.classList.remove('archived', 'spammed');
                item.classList.add('starred');
                showToast('Starred ⭐');
            }}
            localStorage.setItem('starredTweets', JSON.stringify(starredItems));
            localStorage.setItem('archivedTweets', JSON.stringify(archivedItems));
            localStorage.setItem('spamTweets', JSON.stringify(spamItems));
            updateCounts();
            applyFilters();
        }}

        function archiveItem(id) {{
            const item = document.querySelector(`.item[data-id="${{id}}"]`);
            archivedItems[id] = true;
            delete starredItems[id];
            delete spamItems[id];
            item.classList.remove('starred', 'spammed');
            item.classList.add('archived');

            localStorage.setItem('archivedTweets', JSON.stringify(archivedItems));
            localStorage.setItem('starredTweets', JSON.stringify(starredItems));
            localStorage.setItem('spamTweets', JSON.stringify(spamItems));
            updateCounts();
            applyFilters();
            showToast('Archived');
        }}

        function spamItem(id) {{
            const item = document.querySelector(`.item[data-id="${{id}}"]`);
            spamItems[id] = true;
            delete starredItems[id];
            delete archivedItems[id];
            item.classList.remove('starred', 'archived');
            item.classList.add('spammed');

            localStorage.setItem('spamTweets', JSON.stringify(spamItems));
            localStorage.setItem('starredTweets', JSON.stringify(starredItems));
            localStorage.setItem('archivedTweets', JSON.stringify(archivedItems));
            updateCounts();
            applyFilters();
            showToast('Marked as spam');
        }}

        function restoreItem(id) {{
            const item = document.querySelector(`.item[data-id="${{id}}"]`);
            delete starredItems[id];
            delete archivedItems[id];
            delete spamItems[id];
            item.classList.remove('starred', 'archived', 'spammed');

            localStorage.setItem('starredTweets', JSON.stringify(starredItems));
            localStorage.setItem('archivedTweets', JSON.stringify(archivedItems));
            localStorage.setItem('spamTweets', JSON.stringify(spamItems));
            updateCounts();
            applyFilters();
            showToast('Restored to inbox');
        }}

        function toggleNote(id) {{
            const noteInput = document.getElementById(`note-input-${{id}}`);
            noteInput.classList.toggle('visible');
            if (noteInput.classList.contains('visible')) {{
                const input = noteInput.querySelector('input');
                input.value = tweetNotes[id] || '';
                input.focus();
            }}
        }}

        function saveNote(id, event) {{
            if (event.key === 'Enter') {{
                const note = event.target.value.trim();
                const item = document.querySelector(`.item[data-id="${{id}}"]`);
                if (note) {{
                    tweetNotes[id] = note;
                    localStorage.setItem('tweetNotes', JSON.stringify(tweetNotes));
                    const noteEl = document.getElementById(`note-${{id}}`);
                    noteEl.textContent = '📝 ' + note;
                    noteEl.classList.add('visible');
                    item.dataset.hasNote = 'true';
                    if (starredItems[id]) {{
                        starredItems[id].note = note;
                        localStorage.setItem('starredTweets', JSON.stringify(starredItems));
                    }}
                    showToast('Note saved');
                }} else {{
                    delete tweetNotes[id];
                    localStorage.setItem('tweetNotes', JSON.stringify(tweetNotes));
                    const noteEl = document.getElementById(`note-${{id}}`);
                    noteEl.textContent = '';
                    noteEl.classList.remove('visible');
                    item.dataset.hasNote = 'false';
                    showToast('Note removed');
                }}
                document.getElementById(`note-input-${{id}}`).classList.remove('visible');
                applyFilters();
            }}
        }}

        function setSort(sortType) {{
            currentSort = sortType;
            document.querySelectorAll('.sort-btn').forEach(btn => {{
                btn.classList.toggle('active', btn.dataset.sort === sortType);
            }});
            sortItems();
        }}

        function sortItems() {{
            const container = document.getElementById('items-container');
            const items = [...container.querySelectorAll('.item')];

            items.sort((a, b) => {{
                if (currentSort === 'time') {{
                    return BigInt(b.dataset.timestamp) - BigInt(a.dataset.timestamp);
                }} else if (currentSort === 'priority') {{
                    return parseInt(b.dataset.priority) - parseInt(a.dataset.priority);
                }} else if (currentSort === 'likes') {{
                    return parseInt(b.dataset.likes) - parseInt(a.dataset.likes);
                }}
                return 0;
            }});

            items.forEach(item => container.appendChild(item));
        }}

        function setStatus(status) {{
            currentStatus = status;
            document.querySelectorAll('.status-chip').forEach(chip => {{
                chip.classList.toggle('active', chip.dataset.status === status);
            }});
            applyFilters();
        }}

        function applyFilters() {{
            let visibleCount = 0;

            document.querySelectorAll('.item').forEach(item => {{
                const id = item.dataset.id;
                const isStarred = !!starredItems[id];
                const isArchived = !!archivedItems[id];
                const isSpam = !!spamItems[id];
                const hasNote = item.dataset.hasNote === 'true';

                let show = false;

                // Status filter
                if (currentStatus === 'inbox') {{
                    show = !isArchived && !isSpam;
                }} else if (currentStatus === 'starred') {{
                    show = isStarred;
                }} else if (currentStatus === 'archived') {{
                    show = isArchived;
                }} else if (currentStatus === 'spam') {{
                    show = isSpam;
                }} else if (currentStatus === 'notes') {{
                    show = hasNote;
                }}

                item.classList.toggle('hidden', !show);
                if (show) visibleCount++;
            }});

            document.getElementById('visible-count').textContent = visibleCount + ' showing';
            document.getElementById('empty-state').style.display = visibleCount === 0 ? 'block' : 'none';
        }}

        function updateCounts() {{
            const total = document.querySelectorAll('.item').length;
            const starredCount = Object.keys(starredItems).length;
            const archivedCount = Object.keys(archivedItems).length;
            const spamCount = Object.keys(spamItems).length;
            const inboxCount = total - archivedCount - spamCount;

            document.getElementById('inbox-count').textContent = inboxCount;
            document.getElementById('starred-count').textContent = starredCount;
            document.getElementById('archived-count').textContent = archivedCount;
            document.getElementById('spam-count').textContent = spamCount;
        }}

        function copyVisible() {{
            const items = [...document.querySelectorAll('.item:not(.hidden)')];
            const texts = items.map(item => {{
                const id = item.dataset.id;
                const note = tweetNotes[id] ? ` [Note: ${{tweetNotes[id]}}]` : '';
                const starred = starredItems[id] ? '⭐ ' : '';
                return `${{starred}}@${{item.dataset.username}}: ${{item.dataset.text}}${{note}}`;
            }});

            if (texts.length === 0) {{
                showToast('No items to copy');
                return;
            }}

            navigator.clipboard.writeText(`Feedback (${{texts.length}} items):\\n\\n` + texts.join('\\n\\n'));
            showToast(`Copied ${{texts.length}} items`);
        }}

        function showToast(message) {{
            const toast = document.getElementById('toast');
            toast.textContent = message;
            toast.classList.add('visible');
            setTimeout(() => toast.classList.remove('visible'), 2000);
        }}

        async function addTweet() {{
            const input = document.getElementById('tweet-url-input');
            const btn = document.getElementById('add-btn');
            const url = input.value.trim();

            if (!url) {{
                showToast('Please enter a tweet URL');
                return;
            }}

            // Validate URL format
            if (!url.match(/\\/status\\/\\d+/)) {{
                showToast('Invalid tweet URL');
                return;
            }}

            btn.disabled = true;
            btn.classList.add('loading');
            btn.innerHTML = '<svg class="spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle></svg> Fetching...';
            showToast('Fetching replies & quotes...');

            try {{
                const response = await fetch('/api/add', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ url: url }})
                }});

                const result = await response.json();

                if (result.success) {{
                    showToast(`Added ${{result.count}} items!`);
                    input.value = '';
                    setTimeout(() => location.reload(), 1000);
                }} else {{
                    showToast('Error: ' + (result.error || 'Unknown error'));
                }}
            }} catch (e) {{
                showToast('Error: ' + e.message);
            }} finally {{
                btn.disabled = false;
                btn.classList.remove('loading');
                btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg> Add Tweet';
            }}
        }}

        async function refreshAll() {{
            const btn = document.getElementById('refresh-btn');
            const svg = btn.querySelector('svg');

            btn.disabled = true;
            svg.classList.add('spinning');
            btn.innerHTML = '<svg class="spinning" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg> Refreshing...';
            showToast('Fetching latest replies...');

            try {{
                const response = await fetch('/api/refresh', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }}
                }});

                const result = await response.json();

                if (result.success) {{
                    if (result.total_new > 0) {{
                        showToast(`Found ${{result.total_new}} new items!`);
                        setTimeout(() => location.reload(), 1000);
                    }} else {{
                        showToast('No new replies');
                    }}
                }} else {{
                    showToast('Error: ' + (result.error || 'Unknown error'));
                }}
            }} catch (e) {{
                showToast('Error: ' + e.message);
            }} finally {{
                btn.disabled = false;
                btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg> Refresh';
            }}
        }}

        // Allow Enter key to submit
        document.getElementById('tweet-url-input').addEventListener('keydown', (e) => {{
            if (e.key === 'Enter') addTweet();
        }});

        init();
        sortItems();

        // Auto-refresh every 60s (longer interval for stability)
        setTimeout(() => location.reload(), 60000);
    </script>
</body>
</html>'''


def add_tweet(tweet_url):
    """Fetch replies and quotes for a tweet, then run analysis."""
    # Extract tweet ID
    match = re.search(r'/status/(\d+)', tweet_url)
    if not match:
        return {"success": False, "error": "Invalid tweet URL"}

    tweet_id = match.group(1)

    try:
        # Run fetch.py
        fetch_result = subprocess.run(
            ["python3", str(PROJECT_DIR / "fetch.py"), tweet_url],
            capture_output=True,
            text=True,
            timeout=120
        )

        if fetch_result.returncode != 0:
            return {"success": False, "error": f"Fetch failed: {fetch_result.stderr[:200]}"}

        # Run analyze.py
        analyze_result = subprocess.run(
            ["python3", str(PROJECT_DIR / "analyze.py"), tweet_url],
            capture_output=True,
            text=True,
            timeout=60
        )

        # Count items added
        conn = sqlite3.connect(DB_PATH)
        count = conn.execute("SELECT COUNT(*) FROM tweets WHERE parent_tweet_id = ?", [tweet_id]).fetchone()[0]
        conn.close()

        return {"success": True, "count": count, "tweet_id": tweet_id}

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Fetch timed out (>2 min)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def refresh_all_tweets():
    """Incremental fetch for all tracked tweets."""
    tweet_ids = get_tracked_tweets()
    if not tweet_ids:
        return {"success": False, "error": "No tweets being tracked"}

    results = []
    total_new = 0

    for tweet_id in tweet_ids:
        tweet_url = f"https://x.com/i/status/{tweet_id}"
        try:
            # Get count before
            conn = sqlite3.connect(DB_PATH)
            before = conn.execute("SELECT COUNT(*) FROM tweets WHERE parent_tweet_id = ?", [tweet_id]).fetchone()[0]
            conn.close()

            # Run incremental fetch
            fetch_result = subprocess.run(
                ["python3", str(PROJECT_DIR / "fetch.py"), tweet_url],
                capture_output=True,
                text=True,
                timeout=120
            )

            # Run analyze on new items
            subprocess.run(
                ["python3", str(PROJECT_DIR / "analyze.py"), tweet_url],
                capture_output=True,
                text=True,
                timeout=60
            )

            # Get count after
            conn = sqlite3.connect(DB_PATH)
            after = conn.execute("SELECT COUNT(*) FROM tweets WHERE parent_tweet_id = ?", [tweet_id]).fetchone()[0]
            conn.close()

            new_count = after - before
            total_new += new_count
            results.append({"tweet_id": tweet_id, "new": new_count})

        except subprocess.TimeoutExpired:
            results.append({"tweet_id": tweet_id, "error": "timeout"})
        except Exception as e:
            results.append({"tweet_id": tweet_id, "error": str(e)})

    return {"success": True, "total_new": total_new, "results": results}


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

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/add":
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')

            try:
                data = json.loads(body)
                tweet_url = data.get('url', '')

                result = add_tweet(tweet_url)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())
        elif path == "/api/refresh":
            try:
                result = refresh_all_tweets()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress logging


def main():
    port = 8765
    server = HTTPServer(("localhost", port), DashboardHandler)
    print(f"Dashboard: http://localhost:{port}")

    # Open browser after short delay
    def open_browser():
        import time
        time.sleep(0.5)
        webbrowser.open(f"http://localhost:{port}")

    threading.Thread(target=open_browser, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
