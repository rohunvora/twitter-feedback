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


def format_relative_time(iso_timestamp):
    """Convert ISO timestamp to relative time like '2h ago', '3d ago'."""
    if not iso_timestamp:
        return ""
    try:
        # Parse ISO format (Twitter uses 2024-01-15T10:30:00.000Z)
        ts = iso_timestamp.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts.replace(".000", ""))
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        diff = now - dt

        seconds = diff.total_seconds()
        if seconds < 60:
            return "now"
        elif seconds < 3600:
            mins = int(seconds / 60)
            return f"{mins}m"
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f"{hours}h"
        elif seconds < 604800:
            days = int(seconds / 86400)
            return f"{days}d"
        else:
            weeks = int(seconds / 604800)
            return f"{weeks}w"
    except:
        return ""


# Colors for parent tweet indicators
PARENT_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899']

def get_tracked_tweets():
    """Get list of parent tweet IDs being tracked with metadata."""
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    result = conn.execute("""
        SELECT parent_tweet_id, COUNT(*) as count,
               MIN(created_at) as first_reply
        FROM tweets
        GROUP BY parent_tweet_id
        ORDER BY MIN(CAST(id AS INTEGER)) DESC
    """).fetchall()
    conn.close()

    tweets = []
    for i, r in enumerate(result):
        tweets.append({
            'id': r[0],
            'count': r[1],
            'color': PARENT_COLORS[i % len(PARENT_COLORS)],
            'label': f"Tweet {i+1}"
        })
    return tweets


def get_dashboard_data():
    """Get all data for the dashboard."""
    tracked_tweets = get_tracked_tweets()
    if not tracked_tweets:
        return {"items": [], "total": 0, "tracked_tweets": [], "parent_map": {}, "last_updated": datetime.now().isoformat()}

    tweet_ids = [t['id'] for t in tracked_tweets]
    parent_map = {t['id']: t for t in tracked_tweets}

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
        "tracked_tweets": tracked_tweets,
        "parent_map": parent_map,
        "last_updated": datetime.now().isoformat()
    }


def highlight_keywords(text):
    """Highlight actionable keywords in text."""
    keywords = {
        'bug': '#ef4444',
        'broken': '#ef4444',
        'error': '#ef4444',
        'issue': '#ef4444',
        'fix': '#ef4444',
        'feature': '#8b5cf6',
        'please': '#3b82f6',
        'help': '#3b82f6',
        'how': '#3b82f6',
        'why': '#f59e0b',
        'love': '#10b981',
        'great': '#10b981',
        'amazing': '#10b981',
        'thanks': '#10b981',
    }
    for word, color in keywords.items():
        # Case-insensitive replacement with highlighting
        pattern = re.compile(rf'\b({word})\b', re.IGNORECASE)
        text = pattern.sub(rf'<mark style="background:{color}20;color:{color};padding:1px 3px;border-radius:3px">\1</mark>', text)
    return text


def render_dashboard():
    """Render the HTML dashboard."""
    data = get_dashboard_data()
    parent_map = data.get('parent_map', {})

    # Build items HTML with data attributes for sorting
    items_html = ""
    for item in data["items"]:
        text_raw = item["text"].replace("<", "&lt;").replace(">", "&gt;")
        text_preview = text_raw[:140] + "..." if len(text_raw) > 140 else text_raw
        text_highlighted = highlight_keywords(text_preview)
        text_full_highlighted = highlight_keywords(text_raw)
        text_escaped = text_raw.replace("'", "\\'").replace('"', '\\"').replace('\n', ' ')
        is_truncated = len(text_raw) > 140
        metrics = json.loads(item["metrics"]) if item["metrics"] else {}
        likes = metrics.get("like_count", 0)
        tweet_url = f"https://x.com/{item['author_username']}/status/{item['id']}"
        priority = item.get("priority", 0)
        timestamp = item['id']
        relative_time = format_relative_time(item.get('created_at', ''))

        # Parent tweet indicator
        parent_info = parent_map.get(item['parent_tweet_id'], {})
        parent_color = parent_info.get('color', '#94a3b8')
        parent_label = parent_info.get('label', '')

        items_html += f'''
        <div class="item" data-id="{item['id']}" data-username="{item['author_username']}"
             data-text="{text_escaped}" data-priority="{priority}" data-timestamp="{timestamp}"
             data-likes="{likes}" data-parent="{item['parent_tweet_id']}" tabindex="0">
            <div class="parent-indicator" style="background:{parent_color}" title="{parent_label}"></div>
            <img class="avatar" src="https://unavatar.io/twitter/{item['author_username']}" alt="" loading="lazy" onerror="this.src='https://abs.twimg.com/sticky/default_profile_images/default_profile_normal.png'">
            <div class="item-content">
                <div class="item-header">
                    <a href="{tweet_url}" target="_blank" class="username">@{item["author_username"]}</a>
                    {f'<span class="likes">♥ {likes}</span>' if likes > 0 else ''}
                    {f'<span class="timestamp">{relative_time}</span>' if relative_time else ''}
                </div>
                <div class="item-text" onclick="toggleExpand(this)">{text_highlighted}</div>
                {f'<div class="item-text-full">{text_full_highlighted}</div>' if is_truncated else ''}
                <div class="item-note" id="note-{item['id']}"></div>
            </div>
            <div class="item-actions">
                <button class="action-btn star" onclick="starItem('{item['id']}')" title="Star (s)">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg>
                </button>
                <button class="action-btn archive" onclick="archiveItem('{item['id']}')" title="Archive (a)">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="21 8 21 21 3 21 3 8"></polyline><rect x="1" y="3" width="22" height="5"></rect><line x1="10" y1="12" x2="14" y2="12"></line></svg>
                </button>
                <button class="action-btn spam" onclick="spamItem('{item['id']}')" title="Spam (x)">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                </button>
                <button class="action-btn note" onclick="toggleNote('{item['id']}')" title="Note (n)">
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

        .timestamp {{
            font-size: 12px;
            color: #94a3b8;
            margin-left: auto;
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

        /* Parent indicator */
        .parent-indicator {{
            width: 4px;
            flex-shrink: 0;
            border-radius: 2px;
            align-self: stretch;
        }}

        .avatar {{
            width: 40px;
            height: 40px;
            border-radius: 50%;
            flex-shrink: 0;
            margin-right: 12px;
            background: #e2e8f0;
            object-fit: cover;
        }}

        /* Full text expand */
        .item-text {{
            cursor: pointer;
        }}

        .item-text-full {{
            display: none;
            color: #475569;
            font-size: 14px;
            line-height: 1.5;
            margin-top: 8px;
            padding: 12px;
            background: #f8fafc;
            border-radius: 6px;
        }}

        .item.expanded .item-text {{
            display: none;
        }}

        .item.expanded .item-text-full {{
            display: block;
        }}

        /* Actions - always visible */
        .item-actions {{
            display: flex;
            gap: 4px;
            opacity: 0.4;
            transition: opacity 0.15s;
        }}

        .item:hover .item-actions,
        .item:focus .item-actions,
        .item.selected .item-actions {{
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

        /* New item animation */
        .item.new-item {{
            opacity: 0;
            transform: translateY(-10px);
            background: #ecfdf5;
            transition: opacity 0.3s, transform 0.3s, background 2s;
        }}

        .item.new-item.visible {{
            opacity: 1;
            transform: translateY(0);
        }}

        .new-badge {{
            background: #10b981;
            color: #fff;
            font-size: 10px;
            font-weight: 600;
            padding: 2px 6px;
            border-radius: 4px;
            text-transform: uppercase;
        }}

        /* Search bar */
        .search-bar {{
            display: flex;
            gap: 8px;
            margin-bottom: 16px;
        }}

        .search-input {{
            flex: 1;
            padding: 10px 14px;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            font-size: 14px;
            outline: none;
            background: #fff;
        }}

        .search-input:focus {{
            border-color: #3b82f6;
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
        }}

        .search-input::placeholder {{
            color: #94a3b8;
        }}

        /* Selected item for keyboard nav */
        .item.selected {{
            background: #eff6ff;
            box-shadow: inset 0 0 0 2px #3b82f6;
        }}

        /* Keyboard hint */
        .keyboard-hint {{
            display: flex;
            gap: 16px;
            padding: 8px 16px;
            background: #f8fafc;
            border-radius: 6px;
            font-size: 12px;
            color: #64748b;
            margin-bottom: 16px;
        }}

        .keyboard-hint kbd {{
            background: #fff;
            border: 1px solid #e2e8f0;
            border-radius: 4px;
            padding: 2px 6px;
            font-family: monospace;
            font-size: 11px;
            margin-right: 4px;
        }}

        /* Undo toast */
        .toast.with-undo {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}

        .toast .undo-btn {{
            background: #fff;
            color: #1e293b;
            border: none;
            padding: 4px 12px;
            border-radius: 4px;
            font-size: 13px;
            cursor: pointer;
            font-weight: 500;
        }}

        .toast .undo-btn:hover {{
            background: #f1f5f9;
        }}

        /* Parent legend */
        .parent-legend {{
            display: flex;
            gap: 12px;
            padding: 8px 16px;
            background: #fff;
            border-radius: 6px;
            border: 1px solid #e2e8f0;
            margin-bottom: 16px;
            font-size: 13px;
        }}

        .parent-legend-item {{
            display: flex;
            align-items: center;
            gap: 6px;
        }}

        .parent-legend-dot {{
            width: 8px;
            height: 8px;
            border-radius: 2px;
        }}

        .parent-legend-link {{
            color: #64748b;
            text-decoration: none;
        }}

        .parent-legend-link:hover {{
            color: #1e293b;
            text-decoration: underline;
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

        <div class="parent-legend">
            <span style="color:#94a3b8">Tracking:</span>
            {''.join(f'<div class="parent-legend-item"><div class="parent-legend-dot" style="background:{t["color"]}"></div><a href="https://x.com/i/status/{t["id"]}" target="_blank" class="parent-legend-link">{t["label"]} ({t["count"]})</a></div>' for t in data.get('tracked_tweets', []))}
        </div>

        <div class="search-bar">
            <input type="text" class="search-input" id="search-input" placeholder="Search feedback... (try: bug, feature, help)" oninput="filterBySearch(this.value)" />
        </div>

        <div class="keyboard-hint">
            <span><kbd>j</kbd><kbd>k</kbd> navigate</span>
            <span><kbd>s</kbd> star</span>
            <span><kbd>a</kbd> archive</span>
            <span><kbd>x</kbd> spam</span>
            <span><kbd>n</kbd> note</span>
            <span><kbd>o</kbd> open tweet</span>
            <span><kbd>e</kbd> expand</span>
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
            <button class="copy-btn" onclick="copyStarred()">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                Copy Starred
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
        let currentSearch = '';
        let selectedIndex = -1;
        let lastAction = null; // For undo

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
            lastAction = {{ type: 'archive', id, wasStarred: !!starredItems[id] }};

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
            showToastWithUndo('Archived');
            moveToNextVisible();
        }}

        function spamItem(id) {{
            const item = document.querySelector(`.item[data-id="${{id}}"]`);
            lastAction = {{ type: 'spam', id, wasStarred: !!starredItems[id] }};

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
            showToastWithUndo('Marked as spam');
            moveToNextVisible();
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
                const text = (item.dataset.text || '').toLowerCase();
                const username = (item.dataset.username || '').toLowerCase();

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

                // Search filter (AND with status filter)
                if (show && currentSearch) {{
                    show = text.includes(currentSearch) || username.includes(currentSearch);
                }}

                item.classList.toggle('hidden', !show);
                if (show) visibleCount++;
            }});

            document.getElementById('visible-count').textContent = visibleCount + ' showing';
            document.getElementById('empty-state').style.display = visibleCount === 0 ? 'block' : 'none';

            // Reset selection when filters change
            selectedIndex = -1;
            document.querySelectorAll('.item.selected').forEach(el => el.classList.remove('selected'));
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

        function copyStarred() {{
            const starredIds = Object.keys(starredItems);
            if (starredIds.length === 0) {{
                showToast('No starred items to copy');
                return;
            }}

            const texts = starredIds.map(id => {{
                const data = starredItems[id];
                const note = data.note ? ` [Note: ${{data.note}}]` : '';
                return `@${{data.username}}: ${{data.text}}${{note}}`;
            }});

            navigator.clipboard.writeText(`Starred Feedback (${{texts.length}} items):\\n\\n` + texts.join('\\n\\n'));
            showToast(`Copied ${{texts.length}} starred items`);
        }}

        function showToast(message) {{
            const toast = document.getElementById('toast');
            toast.className = 'toast';
            toast.textContent = message;
            toast.classList.add('visible');
            setTimeout(() => toast.classList.remove('visible'), 2000);
        }}

        function showToastWithUndo(message) {{
            const toast = document.getElementById('toast');
            toast.className = 'toast with-undo';
            toast.innerHTML = `<span>${{message}}</span><button class="undo-btn" onclick="undoLastAction()">Undo</button>`;
            toast.classList.add('visible');
            setTimeout(() => {{
                toast.classList.remove('visible');
                lastAction = null;
            }}, 4000);
        }}

        function undoLastAction() {{
            if (!lastAction) return;
            const {{ type, id, wasStarred }} = lastAction;
            const item = document.querySelector(`.item[data-id="${{id}}"]`);

            if (type === 'archive') {{
                delete archivedItems[id];
                item.classList.remove('archived');
            }} else if (type === 'spam') {{
                delete spamItems[id];
                item.classList.remove('spammed');
            }}

            if (wasStarred) {{
                item.classList.add('starred');
            }}

            localStorage.setItem('archivedTweets', JSON.stringify(archivedItems));
            localStorage.setItem('spamTweets', JSON.stringify(spamItems));
            updateCounts();
            applyFilters();
            showToast('Undone');
            lastAction = null;
        }}

        // Search filtering
        function filterBySearch(query) {{
            currentSearch = query.toLowerCase();
            applyFilters();
        }}

        // Expand/collapse full text
        function toggleExpand(el) {{
            const item = el.closest('.item');
            item.classList.toggle('expanded');
        }}

        // Keyboard navigation
        function getVisibleItems() {{
            return [...document.querySelectorAll('.item:not(.hidden)')];
        }}

        function selectItem(index) {{
            const items = getVisibleItems();
            if (items.length === 0) return;

            // Deselect previous
            document.querySelectorAll('.item.selected').forEach(el => el.classList.remove('selected'));

            // Clamp index
            selectedIndex = Math.max(0, Math.min(index, items.length - 1));
            const item = items[selectedIndex];
            item.classList.add('selected');
            item.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
        }}

        function moveToNextVisible() {{
            const items = getVisibleItems();
            if (selectedIndex >= 0 && selectedIndex < items.length - 1) {{
                selectItem(selectedIndex);
            }}
        }}

        function getSelectedId() {{
            const items = getVisibleItems();
            if (selectedIndex >= 0 && selectedIndex < items.length) {{
                return items[selectedIndex].dataset.id;
            }}
            return null;
        }}

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {{
            // Ignore if typing in input
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

            const key = e.key.toLowerCase();

            if (key === 'j') {{
                e.preventDefault();
                selectItem(selectedIndex + 1);
            }} else if (key === 'k') {{
                e.preventDefault();
                selectItem(selectedIndex - 1);
            }} else if (key === 's') {{
                e.preventDefault();
                const id = getSelectedId();
                if (id) starItem(id);
            }} else if (key === 'a') {{
                e.preventDefault();
                const id = getSelectedId();
                if (id) archiveItem(id);
            }} else if (key === 'x') {{
                e.preventDefault();
                const id = getSelectedId();
                if (id) spamItem(id);
            }} else if (key === 'n') {{
                e.preventDefault();
                const id = getSelectedId();
                if (id) toggleNote(id);
            }} else if (key === 'o') {{
                e.preventDefault();
                const items = getVisibleItems();
                if (selectedIndex >= 0 && selectedIndex < items.length) {{
                    const link = items[selectedIndex].querySelector('.username');
                    if (link) window.open(link.href, '_blank');
                }}
            }} else if (key === 'e') {{
                e.preventDefault();
                const items = getVisibleItems();
                if (selectedIndex >= 0 && selectedIndex < items.length) {{
                    const textEl = items[selectedIndex].querySelector('.item-text');
                    if (textEl) toggleExpand(textEl);
                }}
            }} else if (key === 'z' && (e.metaKey || e.ctrlKey)) {{
                e.preventDefault();
                undoLastAction();
            }} else if (key === '/' || key === 'f' && (e.metaKey || e.ctrlKey)) {{
                e.preventDefault();
                document.getElementById('search-input').focus();
            }}
        }});

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

        function formatRelativeTime(isoTimestamp) {{
            if (!isoTimestamp) return '';
            try {{
                const dt = new Date(isoTimestamp);
                const now = new Date();
                const seconds = (now - dt) / 1000;
                if (seconds < 60) return 'now';
                if (seconds < 3600) return Math.floor(seconds / 60) + 'm';
                if (seconds < 86400) return Math.floor(seconds / 3600) + 'h';
                if (seconds < 604800) return Math.floor(seconds / 86400) + 'd';
                return Math.floor(seconds / 604800) + 'w';
            }} catch (e) {{ return ''; }}
        }}

        function createItemElement(item) {{
            const text = item.text.replace(/</g, '&lt;').replace(/>/g, '&gt;');
            const textPreview = text.length > 140 ? text.slice(0, 140) + '...' : text;
            const textEscaped = text.replace(/'/g, "\\'").replace(/"/g, '\\"').replace(/\\n/g, ' ');
            const metrics = typeof item.metrics === 'string' ? JSON.parse(item.metrics) : (item.metrics || {{}});
            const likes = metrics.like_count || 0;
            const tweetUrl = `https://x.com/${{item.author_username}}/status/${{item.id}}`;
            const relativeTime = formatRelativeTime(item.created_at);

            const div = document.createElement('div');
            div.className = 'item new-item';
            div.dataset.id = item.id;
            div.dataset.username = item.author_username;
            div.dataset.text = textEscaped;
            div.dataset.priority = item.priority || 0;
            div.dataset.timestamp = item.id;
            div.dataset.likes = likes;

            div.innerHTML = `
                <div class="parent-indicator" style="background:#10b981"></div>
                <img class="avatar" src="https://unavatar.io/twitter/${{item.author_username}}" alt="" loading="lazy" onerror="this.src='https://abs.twimg.com/sticky/default_profile_images/default_profile_normal.png'">
                <div class="item-content">
                    <div class="item-header">
                        <a href="${{tweetUrl}}" target="_blank" class="username">@${{item.author_username}}</a>
                        ${{likes > 0 ? `<span class="likes">♥ ${{likes}}</span>` : ''}}
                        <span class="new-badge">NEW</span>
                        ${{relativeTime ? `<span class="timestamp">${{relativeTime}}</span>` : ''}}
                    </div>
                    <div class="item-text">${{textPreview}}</div>
                    <div class="item-note" id="note-${{item.id}}"></div>
                </div>
                <div class="item-actions">
                    <button class="action-btn star" onclick="starItem('${{item.id}}')" title="Star">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg>
                    </button>
                    <button class="action-btn archive" onclick="archiveItem('${{item.id}}')" title="Archive">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="21 8 21 21 3 21 3 8"></polyline><rect x="1" y="3" width="22" height="5"></rect><line x1="10" y1="12" x2="14" y2="12"></line></svg>
                    </button>
                    <button class="action-btn spam" onclick="spamItem('${{item.id}}')" title="Spam/Irrelevant">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                    </button>
                    <button class="action-btn note" onclick="toggleNote('${{item.id}}')" title="Add note">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                    </button>
                </div>
                <div class="note-input" id="note-input-${{item.id}}">
                    <input type="text" placeholder="Add a note..." onkeydown="saveNote('${{item.id}}', event)">
                </div>
            `;
            return div;
        }}

        function refreshAll() {{
            const btn = document.getElementById('refresh-btn');
            const container = document.getElementById('items-container');

            btn.disabled = true;
            btn.innerHTML = '<svg class="spinning" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg> Checking...';

            const eventSource = new EventSource('/api/refresh-stream');
            let totalNew = 0;

            eventSource.onmessage = (event) => {{
                const data = JSON.parse(event.data);

                if (data.type === 'fetching') {{
                    btn.innerHTML = `<svg class="spinning" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg> ${{data.index}}/${{data.total}}`;
                }}
                else if (data.type === 'new_items') {{
                    // Insert new items at the top with animation
                    const emptyState = document.getElementById('empty-state');
                    data.items.forEach(item => {{
                        const el = createItemElement(item);
                        if (emptyState) {{
                            container.insertBefore(el, emptyState);
                        }} else {{
                            container.insertBefore(el, container.firstChild);
                        }}
                        // Trigger animation
                        requestAnimationFrame(() => el.classList.add('visible'));
                    }});
                    totalNew += data.count;
                    showToast(`+${{data.count}} new`);
                    updateCounts();
                    applyFilters();
                }}
                else if (data.type === 'done') {{
                    eventSource.close();
                    btn.disabled = false;
                    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg> Refresh';
                    if (totalNew > 0) {{
                        showToast(`Done! ${{totalNew}} new items`);
                    }} else {{
                        showToast('No new replies');
                    }}
                }}
                else if (data.type === 'error') {{
                    showToast('Error: ' + data.message);
                }}
            }};

            eventSource.onerror = () => {{
                eventSource.close();
                btn.disabled = false;
                btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg> Refresh';
                if (totalNew > 0) {{
                    showToast(`Done! ${{totalNew}} new items`);
                }}
            }};
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


def refresh_all_tweets_stream():
    """Generator that yields SSE events as tweets are fetched."""
    tweet_ids = get_tracked_tweets()
    if not tweet_ids:
        yield f"data: {json.dumps({'type': 'error', 'message': 'No tweets being tracked'})}\n\n"
        return

    total_new = 0

    for i, tweet_id in enumerate(tweet_ids):
        tweet_url = f"https://x.com/i/status/{tweet_id}"

        # Signal we're fetching this tweet
        yield f"data: {json.dumps({'type': 'fetching', 'tweet_id': tweet_id, 'index': i+1, 'total': len(tweet_ids)})}\n\n"

        try:
            # Get existing tweet IDs before fetch
            conn = sqlite3.connect(DB_PATH)
            existing_ids = set(r[0] for r in conn.execute(
                "SELECT id FROM tweets WHERE parent_tweet_id = ?", [tweet_id]
            ).fetchall())
            conn.close()

            # Run incremental fetch
            subprocess.run(
                ["python3", str(PROJECT_DIR / "fetch.py"), tweet_url],
                capture_output=True,
                text=True,
                timeout=120
            )

            # Run analyze
            subprocess.run(
                ["python3", str(PROJECT_DIR / "analyze.py"), tweet_url],
                capture_output=True,
                text=True,
                timeout=60
            )

            # Get new tweets (ones that weren't there before)
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            all_tweets = conn.execute("""
                SELECT t.id, t.author_username, t.text, t.tweet_type, t.metrics, t.created_at,
                       COALESCE(a.priority, 0) as priority, t.parent_tweet_id
                FROM tweets t
                LEFT JOIN analysis a ON t.id = a.tweet_id
                WHERE t.parent_tweet_id = ?
            """, [tweet_id]).fetchall()
            conn.close()

            new_items = []
            for row in all_tweets:
                if row['id'] not in existing_ids:
                    new_items.append({
                        'id': row['id'],
                        'author_username': row['author_username'],
                        'text': row['text'],
                        'metrics': row['metrics'],
                        'priority': row['priority'],
                        'created_at': row['created_at']
                    })

            if new_items:
                total_new += len(new_items)
                yield f"data: {json.dumps({'type': 'new_items', 'items': new_items, 'count': len(new_items)})}\n\n"

        except subprocess.TimeoutExpired:
            yield f"data: {json.dumps({'type': 'error', 'message': f'Timeout fetching {tweet_id}'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    yield f"data: {json.dumps({'type': 'done', 'total_new': total_new})}\n\n"


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
        elif path == "/api/refresh-stream":
            # Server-Sent Events for real-time refresh
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                for event in refresh_all_tweets_stream():
                    self.wfile.write(event.encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass  # Client disconnected
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
