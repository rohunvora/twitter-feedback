#!/usr/bin/env python3
"""
Twitter Feedback Analyzer

Categorizes fetched tweets into actionable categories.

Usage:
    python3 analyze.py <tweet_url_or_id>
    python3 analyze.py <tweet_url_or_id> --show-all
"""

import sqlite3
import sys
import re
from pathlib import Path

# Project root (where this script lives)
PROJECT_DIR = Path(__file__).parent.resolve()

# Database location
DB_PATH = PROJECT_DIR / "data" / "feedback.db"

# Categories for analysis
CATEGORIES = {
    "feature_request": "Suggestions for new features or improvements",
    "question": "Questions about how something works",
    "bug_report": "Reports of issues or problems",
    "praise": "Positive feedback and appreciation",
    "criticism": "Negative feedback or complaints",
    "joke": "Humorous responses, memes",
    "spam": "Promotional content, irrelevant",
    "other": "Doesn't fit other categories"
}


def get_connection():
    """Get SQLite connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_unanalyzed_tweets(conn, parent_tweet_id):
    """Get tweets that haven't been analyzed yet."""
    return conn.execute("""
        SELECT t.id, t.author_username, t.text, t.tweet_type, t.metrics
        FROM tweets t
        LEFT JOIN analysis a ON t.id = a.tweet_id
        WHERE t.parent_tweet_id = ? AND a.tweet_id IS NULL
        ORDER BY CAST(t.id AS INTEGER) DESC
    """, [parent_tweet_id]).fetchall()


def get_all_analysis(conn, parent_tweet_id):
    """Get all analyzed tweets with their categories."""
    return conn.execute("""
        SELECT t.id, t.author_username, t.text, t.tweet_type, a.category, a.summary, a.priority
        FROM tweets t
        JOIN analysis a ON t.id = a.tweet_id
        WHERE t.parent_tweet_id = ?
        ORDER BY a.priority DESC, a.category, CAST(t.id AS INTEGER) DESC
    """, [parent_tweet_id]).fetchall()


def categorize_tweet(text):
    """
    Simple rule-based categorization.
    Returns (category, summary, priority).
    """
    text_lower = text.lower()

    # Feature requests
    if any(phrase in text_lower for phrase in [
        "would be nice", "should add", "can you add", "feature request",
        "it would be great", "please add", "wish it", "want to see",
        "suggestion:", "idea:", "could you"
    ]):
        return "feature_request", "Potential feature suggestion", 2

    # Questions
    if "?" in text and any(word in text_lower for word in [
        "how", "what", "where", "when", "why", "does", "can", "is it", "will"
    ]):
        return "question", "User question", 1

    # Bug reports
    if any(phrase in text_lower for phrase in [
        "doesn't work", "not working", "broken", "bug", "error", "issue",
        "problem", "crash", "fail"
    ]):
        return "bug_report", "Potential issue report", 2

    # Criticism
    if any(phrase in text_lower for phrase in [
        "hate", "terrible", "awful", "worst", "sucks", "disappointed",
        "waste", "useless", "don't like"
    ]):
        return "criticism", "Negative feedback", 1

    # Praise
    if any(phrase in text_lower for phrase in [
        "love", "amazing", "awesome", "great", "perfect", "thank",
        "beautiful", "excellent", "brilliant", "goat", "fire", "based"
    ]):
        return "praise", "Positive feedback", 0

    # Jokes/memes
    if any(phrase in text_lower for phrase in [
        "lol", "lmao", "haha", "bruh", "fr fr", "no cap", "deadass"
    ]) or len(text) < 20:
        return "joke", "Casual/joke response", 0

    # Spam detection
    if any(phrase in text_lower for phrase in [
        "check my", "dm me", "follow me", "$", "crypto", "nft", "airdrop",
        "giveaway", "click here", "join"
    ]):
        return "spam", "Promotional content", 0

    return "other", "General response", 0


def analyze_tweets(parent_tweet_id):
    """Analyze all unanalyzed tweets for a parent tweet."""
    conn = get_connection()

    tweets = get_unanalyzed_tweets(conn, parent_tweet_id)
    if not tweets:
        print("No new tweets to analyze.")
        return 0

    print(f"Analyzing {len(tweets)} tweets...")

    analyzed = 0
    for tweet in tweets:
        category, summary, priority = categorize_tweet(tweet["text"])

        conn.execute("""
            INSERT INTO analysis (tweet_id, category, summary, priority)
            VALUES (?, ?, ?, ?)
        """, [tweet["id"], category, summary, priority])

        analyzed += 1

    conn.commit()
    conn.close()

    return analyzed


def show_analysis(parent_tweet_id, show_all=False):
    """Display analysis results grouped by category."""
    conn = get_connection()

    results = get_all_analysis(conn, parent_tweet_id)
    if not results:
        print("No analyzed tweets found.")
        return

    # Group by category
    by_category = {}
    for row in results:
        cat = row["category"]
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(row)

    # Display summary
    print("\n" + "=" * 60)
    print("FEEDBACK ANALYSIS SUMMARY")
    print("=" * 60)

    for cat in ["feature_request", "question", "bug_report", "criticism", "praise", "joke", "spam", "other"]:
        if cat in by_category:
            count = len(by_category[cat])
            print(f"  {cat:18} {count:4} tweets")

    print("=" * 60)

    # Show high-priority items
    priority_items = [r for r in results if r["priority"] >= 1]
    if priority_items:
        print("\nHIGH PRIORITY ITEMS:")
        print("-" * 60)
        for item in priority_items[:20]:  # Show top 20
            text = item["text"][:100] + "..." if len(item["text"]) > 100 else item["text"]
            text = text.replace("\n", " ")
            print(f"[@{item['author_username']}] ({item['category']})")
            print(f"  {text}")
            print()

    # Optionally show all
    if show_all:
        print("\nALL CATEGORIZED TWEETS:")
        print("-" * 60)
        for cat, items in by_category.items():
            print(f"\n### {cat.upper()} ({len(items)} tweets) ###\n")
            for item in items[:10]:  # Show 10 per category
                text = item["text"][:80] + "..." if len(item["text"]) > 80 else item["text"]
                text = text.replace("\n", " ")
                print(f"  @{item['author_username']}: {text}")

    conn.close()


def extract_tweet_id(input_str):
    """Extract tweet ID from URL or return as-is if already an ID."""
    match = re.search(r'/status/(\d+)', input_str)
    if match:
        return match.group(1)
    if input_str.isdigit():
        return input_str
    raise ValueError(f"Cannot extract tweet ID from: {input_str}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 analyze.py <tweet_url_or_id> [--show-all]")
        sys.exit(1)

    tweet_input = sys.argv[1]
    show_all = "--show-all" in sys.argv

    try:
        parent_tweet_id = extract_tweet_id(tweet_input)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(f"Analyzing feedback for tweet: {parent_tweet_id}")

    # Run analysis
    count = analyze_tweets(parent_tweet_id)
    if count:
        print(f"Analyzed {count} new tweets")

    # Show results
    show_analysis(parent_tweet_id, show_all=show_all)


if __name__ == "__main__":
    main()
