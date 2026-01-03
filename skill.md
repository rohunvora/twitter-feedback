# Twitter Feedback Skill

Fetch and analyze replies/quotes from Twitter posts using the X API v2.

## Usage

```bash
# Fetch new replies and quotes for a tweet
python3 fetch.py <tweet_url_or_id>

# Backfill older replies (after initial fetch)
python3 fetch.py <tweet_url_or_id> --backfill

# Analyze fetched tweets
python3 analyze.py <tweet_url_or_id>
```

## How It Works

1. **Incremental Fetching**: Uses two watermarks per tweet:
   - `replies` / `quotes` - tracks newest fetched ID
   - `replies_oldest` / `quotes_oldest` - tracks oldest fetched ID

2. **Resilience**: Data saved after each page (crash-safe)

3. **Correctness**: Watermarks saved only after successful completion

## Files

```
twitter-feedback/
├── .env            # X_BEARER_TOKEN (not committed)
├── .gitignore      # Ignores .env and database
├── skill.md        # This file
├── fetch.py        # X API fetcher with incremental watermarks
├── analyze.py      # Categorize tweets
└── data/
    └── feedback.db # SQLite database (not committed)
```

## Database Schema

- `tweets` - Raw tweet data (id, parent_tweet_id, tweet_type, author, text, metrics)
- `analysis` - Categorized results (category, summary, priority)
- `ingestion_state` - Watermarks for incremental fetching

## Requirements

- X API Bearer Token in `.env` as `X_BEARER_TOKEN`
- Python 3.9+, httpx, python-dotenv
