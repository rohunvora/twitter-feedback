#!/usr/bin/env python3
"""
Twitter Feedback Insights Generator

Analyzes fetched tweets using Claude and generates an HTML report.

Usage:
    python3 insights.py <tweet_url_or_id>
    python3 insights.py <tweet_url_or_id> --output report.html
"""

import sqlite3
import sys
import re
import os
import json
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

# Project root
PROJECT_DIR = Path(__file__).parent.resolve()
load_dotenv(PROJECT_DIR / ".env")

DB_PATH = PROJECT_DIR / "data" / "feedback.db"
OUTPUT_DIR = PROJECT_DIR / "output"


def get_connection():
    """Get SQLite connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_tweets(conn, parent_tweet_id):
    """Get all tweets for a parent tweet."""
    return conn.execute("""
        SELECT id, author_username, text, tweet_type, metrics, created_at
        FROM tweets
        WHERE parent_tweet_id = ?
        ORDER BY CAST(id AS INTEGER) DESC
    """, [parent_tweet_id]).fetchall()


def format_tweets_for_analysis(tweets):
    """Format tweets for Claude analysis."""
    lines = []
    for t in tweets:
        metrics = json.loads(t["metrics"]) if t["metrics"] else {}
        likes = metrics.get("like_count", 0)
        rts = metrics.get("retweet_count", 0)
        lines.append(f"@{t['author_username']} ({t['tweet_type']}, {likes} likes, {rts} RTs): {t['text']}")
    return "\n".join(lines)


def generate_insights_with_claude(tweets_text, tweet_url, total_count):
    """Generate insights using Claude API."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None, "ANTHROPIC_API_KEY not found in .env"
    
    if not HAS_ANTHROPIC:
        return None, "anthropic package not installed. Run: pip install anthropic"
    
    client = anthropic.Anthropic(api_key=api_key)
    
    prompt = f"""Analyze these {total_count} Twitter/X replies and quote tweets. Generate an HTML insights report.

SOURCE TWEET: {tweet_url}

REPLIES AND QUOTES:
{tweets_text}

Generate a complete HTML document with:
1. Summary stats (total responses, % noise vs signal)
2. Key insights - what's the main narrative/hook that drove engagement?
3. Actionable items - feature requests, questions, partnership offers
4. Noise categories - jokes, spam, drama (collapsed by default)
5. Notable quotes with links back to tweets (format: https://x.com/USERNAME/status/TWEET_ID)

Use this exact HTML structure and styling:
- Clean, light theme with system fonts
- Collapsible <details> sections for long lists
- Tags for categorization (.tag classes)
- Blockquotes for tweet citations
- Stats row at top

Output ONLY the complete HTML document, no explanation."""

    print("  Calling Claude API...")
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}]
    )
    
    html = response.content[0].text
    
    # Extract just the HTML if wrapped in markdown
    if "```html" in html:
        html = html.split("```html")[1].split("```")[0]
    elif "```" in html:
        html = html.split("```")[1].split("```")[0]
    
    return html.strip(), None


def generate_basic_html(tweets, tweet_url, parent_tweet_id):
    """Generate basic HTML report without AI (fallback)."""
    
    # Categorize tweets
    categories = {
        "feature_request": [], "question": [], "praise": [],
        "criticism": [], "bug_report": [], "other": []
    }
    
    for t in tweets:
        text = t["text"].lower()
        if any(w in text for w in ["would be nice", "should add", "can you add", "please add", "feature"]):
            categories["feature_request"].append(t)
        elif "?" in text:
            categories["question"].append(t)
        elif any(w in text for w in ["love", "amazing", "awesome", "great", "perfect"]):
            categories["praise"].append(t)
        elif any(w in text for w in ["hate", "terrible", "awful", "sucks", "worst"]):
            categories["criticism"].append(t)
        elif any(w in text for w in ["bug", "broken", "error", "doesn't work", "not working"]):
            categories["bug_report"].append(t)
        else:
            categories["other"].append(t)
    
    def render_tweets(tweet_list, limit=10):
        html = ""
        for t in tweet_list[:limit]:
            text = t["text"].replace("<", "&lt;").replace(">", "&gt;")
            html += f'<blockquote><a class="cite" href="https://x.com/{t["author_username"]}/status/{t["id"]}">@{t["author_username"]}</a>: {text}</blockquote>\n'
        return html
    
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Tweet Feedback Report</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ max-width: 900px; margin: 40px auto; padding: 0 20px; font-family: system-ui, sans-serif; background: #fff; color: #1a1a1a; line-height: 1.5; }}
    h1 {{ border-bottom: 2px solid #333; padding-bottom: 10px; }}
    h2 {{ margin-top: 32px; border-bottom: 1px solid #ccc; padding-bottom: 8px; }}
    .meta {{ color: #666; font-size: 0.875rem; }}
    .meta a {{ color: #666; }}
    .stats-row {{ display: flex; gap: 2rem; margin: 1rem 0; flex-wrap: wrap; }}
    .stat-box {{ text-align: center; }}
    .stat-box .stat {{ font-size: 28px; font-weight: bold; }}
    .stat-label {{ font-size: 12px; color: #666; }}
    blockquote {{ border-left: 3px solid #ccc; margin: 0.5rem 0; padding: 8px 16px; background: #fafafa; }}
    blockquote a.cite {{ color: #1a1a1a; font-weight: 600; }}
    details {{ margin: 20px 0; padding-bottom: 20px; border-bottom: 1px solid #eee; }}
    summary {{ cursor: pointer; font-size: 1.1em; font-weight: 500; }}
  </style>
</head>
<body>
  <h1>Tweet Feedback Report</h1>
  <p class="meta">{len(tweets)} responses · <a href="{tweet_url}">Original Tweet</a></p>
  
  <div class="stats-row">
    <div class="stat-box"><div class="stat">{len(tweets)}</div><div class="stat-label">Total</div></div>
    <div class="stat-box"><div class="stat">{len(categories["feature_request"])}</div><div class="stat-label">Feature Requests</div></div>
    <div class="stat-box"><div class="stat">{len(categories["question"])}</div><div class="stat-label">Questions</div></div>
    <div class="stat-box"><div class="stat">{len(categories["praise"])}</div><div class="stat-label">Praise</div></div>
  </div>
  
  <h2>Feature Requests ({len(categories["feature_request"])})</h2>
  {render_tweets(categories["feature_request"])}
  
  <h2>Questions ({len(categories["question"])})</h2>
  {render_tweets(categories["question"])}
  
  <details>
    <summary>Praise ({len(categories["praise"])})</summary>
    {render_tweets(categories["praise"])}
  </details>
  
  <details>
    <summary>Criticism ({len(categories["criticism"])})</summary>
    {render_tweets(categories["criticism"])}
  </details>
  
  <details>
    <summary>Other ({len(categories["other"])})</summary>
    {render_tweets(categories["other"], limit=20)}
  </details>
</body>
</html>"""


def extract_tweet_id(input_str):
    """Extract tweet ID from URL or return as-is."""
    match = re.search(r'/status/(\d+)', input_str)
    if match:
        return match.group(1)
    if input_str.isdigit():
        return input_str
    raise ValueError(f"Cannot extract tweet ID from: {input_str}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 insights.py <tweet_url_or_id> [--output file.html]")
        sys.exit(1)
    
    tweet_input = sys.argv[1]
    
    # Parse output file
    output_file = None
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_file = sys.argv[idx + 1]
    
    try:
        parent_tweet_id = extract_tweet_id(tweet_input)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    # Reconstruct tweet URL
    tweet_url = f"https://x.com/i/status/{parent_tweet_id}"
    if "x.com" in tweet_input or "twitter.com" in tweet_input:
        tweet_url = tweet_input
    
    print(f"Generating insights for: {parent_tweet_id}")
    
    # Get tweets from database
    conn = get_connection()
    tweets = get_tweets(conn, parent_tweet_id)
    conn.close()
    
    if not tweets:
        print("No tweets found. Run fetch.py first.")
        sys.exit(1)
    
    print(f"  Found {len(tweets)} tweets")
    
    # Try Claude first, fall back to basic
    tweets_text = format_tweets_for_analysis(tweets)
    html, error = generate_insights_with_claude(tweets_text, tweet_url, len(tweets))
    
    if error:
        print(f"  Note: {error}")
        print("  Generating basic report (no AI)...")
        html = generate_basic_html(tweets, tweet_url, parent_tweet_id)
    
    # Save output
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    if output_file:
        output_path = Path(output_file)
    else:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = OUTPUT_DIR / f"insights-{parent_tweet_id[:8]}-{timestamp}.html"
    
    output_path.write_text(html)
    print(f"\n✓ Report saved: {output_path}")
    print(f"  Open in browser: file://{output_path.resolve()}")


if __name__ == "__main__":
    main()

