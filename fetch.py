#!/usr/bin/env python3
"""
Twitter Feedback Fetcher - X API v2

Fetches replies and quotes for a tweet using incremental watermarks.
Follows incremental-fetch skill patterns for resilience.

Usage:
    python3 fetch.py <tweet_url_or_id>
    python3 fetch.py <tweet_url_or_id> --backfill
"""

import sqlite3
import httpx
import time
import random
import re
import sys
import os
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# ============================================================================
# CONFIGURATION
# ============================================================================

# Project root (where this script lives)
PROJECT_DIR = Path(__file__).parent.resolve()

# Load token from .env in project root
load_dotenv(PROJECT_DIR / ".env")
BEARER_TOKEN = os.getenv("X_BEARER_TOKEN")

# Database location
DB_PATH = PROJECT_DIR / "data" / "feedback.db"

# API settings
API_BASE = "https://api.twitter.com/2"
MAX_PAGES = 50
PAGE_SIZE = 100

# ============================================================================
# DATABASE SETUP
# ============================================================================

def get_connection():
    """Get SQLite connection with proper settings."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn):
    """Initialize database tables."""
    conn.executescript("""
        -- Raw tweet data
        CREATE TABLE IF NOT EXISTS tweets (
            id TEXT PRIMARY KEY,
            parent_tweet_id TEXT NOT NULL,
            tweet_type TEXT NOT NULL,  -- 'reply' or 'quote'
            author_id TEXT,
            author_username TEXT,
            text TEXT,
            created_at TEXT,
            metrics TEXT,  -- JSON: retweets, likes, etc.
            fetched_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_tweets_parent ON tweets(parent_tweet_id);
        CREATE INDEX IF NOT EXISTS idx_tweets_type ON tweets(tweet_type);

        -- Analysis results
        CREATE TABLE IF NOT EXISTS analysis (
            tweet_id TEXT PRIMARY KEY,
            category TEXT,  -- feature_request, question, praise, criticism, joke, spam, other
            summary TEXT,
            priority INTEGER DEFAULT 0,  -- 0=low, 1=medium, 2=high
            analyzed_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (tweet_id) REFERENCES tweets(id)
        );

        -- Ingestion state (watermarks) - follows incremental-fetch pattern
        -- Uses separate rows for each watermark type per parent tweet
        CREATE TABLE IF NOT EXISTS ingestion_state (
            parent_tweet_id TEXT NOT NULL,
            data_type TEXT NOT NULL,  -- 'replies', 'replies_oldest', 'quotes', 'quotes_oldest'
            last_id TEXT,
            updated_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (parent_tweet_id, data_type)
        );
    """)
    conn.commit()


# ============================================================================
# WATERMARK FUNCTIONS (from incremental-fetch patterns)
# ============================================================================

def get_watermark(conn, parent_tweet_id, data_type):
    """Get watermark for a specific data type."""
    result = conn.execute("""
        SELECT last_id FROM ingestion_state
        WHERE parent_tweet_id = ? AND data_type = ?
    """, [parent_tweet_id, data_type]).fetchone()
    return result["last_id"] if result else None


def update_watermark(conn, parent_tweet_id, data_type, last_id):
    """Update watermark (upsert)."""
    conn.execute("""
        INSERT INTO ingestion_state (parent_tweet_id, data_type, last_id, updated_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT (parent_tweet_id, data_type) DO UPDATE SET
            last_id = EXCLUDED.last_id,
            updated_at = datetime('now')
    """, [parent_tweet_id, data_type, last_id])
    conn.commit()


# ============================================================================
# API FUNCTIONS
# ============================================================================

def fetch_with_retry(client, url, params, max_attempts=3):
    """Fetch with exponential backoff and rate limit handling."""
    for attempt in range(max_attempts):
        try:
            response = client.get(url, params=params, timeout=30.0)

            if response.status_code == 429:  # Rate limit
                reset_ts = response.headers.get("x-rate-limit-reset", "0")
                wait = max(0, int(reset_ts) - int(time.time()) + 5)

                if wait > 120:  # Don't wait more than 2 minutes
                    print(f"  Rate limited, skip (wait would be {wait}s)")
                    return None, "rate_limit_skip"

                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue

            if response.status_code != 200:
                print(f"  HTTP {response.status_code}: {response.text[:200]}")
                return None, f"http_{response.status_code}"

            return response.json(), None

        except Exception as e:
            wait = (2 ** attempt) * 5 + random.uniform(0, 3)
            print(f"  Error: {e}, retrying in {wait:.0f}s...")
            time.sleep(wait)

    return None, "max_retries"


def fetch_replies(client, parent_tweet_id, since_id=None, until_id=None, pagination_token=None):
    """Fetch one page of replies using search API."""
    # Build query: replies to this conversation
    query = f"conversation_id:{parent_tweet_id} is:reply"

    params = {
        "query": query,
        "max_results": PAGE_SIZE,
        "tweet.fields": "created_at,public_metrics,author_id",
        "expansions": "author_id",
        "user.fields": "username"
    }

    if since_id:
        params["since_id"] = since_id
    if until_id:
        params["until_id"] = until_id
    if pagination_token:
        params["next_token"] = pagination_token

    data, error = fetch_with_retry(client, f"{API_BASE}/tweets/search/recent", params)

    if error:
        return [], None, error

    tweets = data.get("data", [])

    # Build username lookup from includes
    users = {}
    for user in data.get("includes", {}).get("users", []):
        users[user["id"]] = user["username"]

    # Attach usernames to tweets
    for tweet in tweets:
        tweet["author_username"] = users.get(tweet.get("author_id"), "unknown")

    next_token = data.get("meta", {}).get("next_token")
    return tweets, next_token, None


def fetch_quotes(client, parent_tweet_id, since_id=None, pagination_token=None):
    """Fetch one page of quote tweets."""
    params = {
        "max_results": PAGE_SIZE,
        "tweet.fields": "created_at,public_metrics,author_id",
        "expansions": "author_id",
        "user.fields": "username"
    }

    if pagination_token:
        params["pagination_token"] = pagination_token

    data, error = fetch_with_retry(
        client,
        f"{API_BASE}/tweets/{parent_tweet_id}/quote_tweets",
        params
    )

    if error:
        return [], None, error

    tweets = data.get("data", [])

    # Build username lookup
    users = {}
    for user in data.get("includes", {}).get("users", []):
        users[user["id"]] = user["username"]

    for tweet in tweets:
        tweet["author_username"] = users.get(tweet.get("author_id"), "unknown")

    next_token = data.get("meta", {}).get("next_token")
    return tweets, next_token, None


# ============================================================================
# DATA STORAGE
# ============================================================================

def save_tweets(conn, parent_tweet_id, tweets, tweet_type):
    """Save tweets to database (upsert)."""
    import json

    for tweet in tweets:
        metrics = json.dumps(tweet.get("public_metrics", {}))
        conn.execute("""
            INSERT INTO tweets (id, parent_tweet_id, tweet_type, author_id, author_username, text, created_at, metrics)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                text = EXCLUDED.text,
                metrics = EXCLUDED.metrics,
                fetched_at = datetime('now')
        """, [
            tweet["id"],
            parent_tweet_id,
            tweet_type,
            tweet.get("author_id"),
            tweet.get("author_username"),
            tweet.get("text"),
            tweet.get("created_at"),
            metrics
        ])
    conn.commit()


# ============================================================================
# MAIN FETCH LOOP (incremental-fetch pattern)
# ============================================================================

def fetch_for_tweet(parent_tweet_id, tweet_type, backfill=False):
    """
    Fetch replies or quotes for a tweet.

    Follows incremental-fetch patterns:
    - Save data after EACH page (resilience)
    - Save watermarks ONCE at end (correctness)
    """
    conn = get_connection()
    init_db(conn)

    # Get watermarks (separate rows in DB)
    data_type = "replies" if tweet_type == "reply" else "quotes"
    newest_id = get_watermark(conn, parent_tweet_id, data_type)
    oldest_id = get_watermark(conn, parent_tweet_id, f"{data_type}_oldest")

    # Determine fetch mode
    if backfill and oldest_id:
        since_id = None
        until_id = oldest_id  # Fetch older than this
        mode = "backfill"
    elif newest_id:
        since_id = newest_id  # Fetch newer than this
        until_id = None
        mode = "incremental"
    else:
        since_id = None
        until_id = None
        mode = "initial"

    print(f"\nFetching {tweet_type}s ({mode} mode)...")
    if newest_id:
        print(f"  Newest watermark: {newest_id}")
    if oldest_id:
        print(f"  Oldest watermark: {oldest_id}")

    # Create API client
    client = httpx.Client(headers={"Authorization": f"Bearer {BEARER_TOKEN}"})

    # Track watermarks for THIS run
    run_newest_id = None
    run_oldest_id = None
    pagination_token = None
    total_saved = 0

    try:
        for page in range(MAX_PAGES):
            # Fetch one page
            if tweet_type == "reply":
                tweets, next_token, error = fetch_replies(
                    client, parent_tweet_id,
                    since_id=since_id, until_id=until_id,
                    pagination_token=pagination_token
                )
            else:
                tweets, next_token, error = fetch_quotes(
                    client, parent_tweet_id,
                    since_id=since_id,
                    pagination_token=pagination_token
                )

            if error:
                print(f"  Error: {error}")
                break

            if not tweets:
                print(f"  No more {tweet_type}s found")
                break

            # Track watermarks (compare as INT for numeric IDs)
            for tweet in tweets:
                tweet_id = tweet["id"]
                if run_newest_id is None or int(tweet_id) > int(run_newest_id):
                    run_newest_id = tweet_id
                if run_oldest_id is None or int(tweet_id) < int(run_oldest_id):
                    run_oldest_id = tweet_id

            # SAVE DATA IMMEDIATELY after each page (resilience)
            save_tweets(conn, parent_tweet_id, tweets, tweet_type)
            total_saved += len(tweets)
            print(f"  Page {page + 1}: {len(tweets)} {tweet_type}s saved (total: {total_saved})")

            if not next_token:
                break
            pagination_token = next_token

            # Small delay between pages
            time.sleep(1)

        # UPDATE WATERMARKS ONCE at end (correctness)
        if run_newest_id:
            if newest_id is None or int(run_newest_id) > int(newest_id):
                update_watermark(conn, parent_tweet_id, data_type, run_newest_id)
                print(f"  Updated newest watermark: {run_newest_id}")

        if run_oldest_id:
            if oldest_id is None or int(run_oldest_id) < int(oldest_id):
                update_watermark(conn, parent_tweet_id, f"{data_type}_oldest", run_oldest_id)
                print(f"  Updated oldest watermark: {run_oldest_id}")

    finally:
        client.close()
        conn.close()

    return total_saved


def extract_tweet_id(input_str):
    """Extract tweet ID from URL or return as-is if already an ID."""
    # URL pattern: https://x.com/user/status/1234567890
    match = re.search(r'/status/(\d+)', input_str)
    if match:
        return match.group(1)
    # Already an ID
    if input_str.isdigit():
        return input_str
    raise ValueError(f"Cannot extract tweet ID from: {input_str}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 fetch.py <tweet_url_or_id> [--backfill]")
        sys.exit(1)

    if not BEARER_TOKEN:
        print("Error: X_BEARER_TOKEN not found in /Users/satoshi/twitter-feedback/.env")
        sys.exit(1)

    tweet_input = sys.argv[1]
    backfill = "--backfill" in sys.argv

    try:
        parent_tweet_id = extract_tweet_id(tweet_input)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(f"Fetching feedback for tweet: {parent_tweet_id}")
    print(f"Database: {DB_PATH}")

    # Fetch replies
    replies_count = fetch_for_tweet(parent_tweet_id, "reply", backfill=backfill)

    # Fetch quotes
    quotes_count = fetch_for_tweet(parent_tweet_id, "quote", backfill=backfill)

    print(f"\n{'='*50}")
    print(f"Done! Saved {replies_count} replies + {quotes_count} quotes")
    print(f"Database: {DB_PATH}")


if __name__ == "__main__":
    main()
