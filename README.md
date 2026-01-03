# Twitter Feedback Analyzer

Fetch replies and quotes to any tweet, then generate an AI-powered insights report.

```bash
# 1. Fetch replies & quotes
python fetch.py https://x.com/username/status/123456789

# 2. Generate insights report
python insights.py https://x.com/username/status/123456789
```

Opens an HTML report with categorized feedback, actionable items, and noise filtered out.

---

## Setup

**Requirements:** Python 3.9+, X API Bearer Token

```bash
git clone https://github.com/rohunvora/twitter-feedback.git
cd twitter-feedback
pip install -r requirements.txt
```

Create `.env` with your X API credentials:

```
X_BEARER_TOKEN=your_bearer_token_here
ANTHROPIC_API_KEY=your_key_here  # optional, for AI insights
```

### Getting an X API Bearer Token

1. Go to [developer.x.com](https://developer.x.com)
2. Create a project and app
3. Generate a Bearer Token from the "Keys and tokens" tab

---

## Usage

### Fetch tweets

```bash
# Fetch new replies and quotes
python fetch.py https://x.com/user/status/123456789

# Backfill older replies (run after initial fetch)
python fetch.py https://x.com/user/status/123456789 --backfill
```

### Generate insights

```bash
# Generate HTML report (uses Claude if ANTHROPIC_API_KEY is set)
python insights.py https://x.com/user/status/123456789

# Save to specific file
python insights.py https://x.com/user/status/123456789 --output report.html
```

### Basic analysis (no AI)

```bash
# Quick categorization without API calls
python analyze.py https://x.com/user/status/123456789
```

---

## How it works

1. **Incremental fetching** - Uses watermarks to only fetch new tweets on subsequent runs
2. **Crash-safe** - Data saved after each API page, watermarks saved at end
3. **AI-powered insights** - Claude analyzes sentiment, extracts feature requests, filters noise

## Files

```
twitter-feedback/
├── fetch.py        # X API fetcher with incremental watermarks
├── analyze.py      # Basic rule-based categorization
├── insights.py     # AI-powered HTML report generator
├── data/
│   └── feedback.db # SQLite database (auto-created)
└── output/         # Generated reports
```

## License

MIT

