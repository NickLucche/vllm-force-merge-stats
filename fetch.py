#!/usr/bin/env python3
"""Fetch recently merged vLLM PRs and flag force-merges.

A "force-merge" in vLLM is a merge performed by the `vllm-bot` account, which
lead maintainers use to override CI (see the project governance docs). This is
the only reliable signal: every PR is squash-merged with committer
`GitHub <noreply@github.com>`, so git history cannot distinguish a force-merge
from a normal merge. The GitHub `mergedBy` field can.

This script paginates the GitHub GraphQL search API over a date range (chunked
by week to stay under the 1000-results-per-search cap) and writes `data.json`,
consumed by `index.html`.

Auth: uses your existing `gh` login via `gh auth token` (no token handling).

Usage:
    python3 fetch.py            # last 182 days (~6 months)
    python3 fetch.py --days 365
"""

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.request

REPO_OWNER = "vllm-project"
REPO_NAME = "vllm"
FORCE_MERGE_LOGIN = "vllm-bot"
GRAPHQL_URL = "https://api.github.com/graphql"

QUERY = """
query($q: String!, $cursor: String) {
  search(query: $q, type: ISSUE, first: 100, after: $cursor) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
        number
        title
        url
        mergedAt
        author { login }
        mergedBy { login }
      }
    }
  }
}
"""


def gh_token() -> str:
    """Token from GITHUB_TOKEN/GH_TOKEN (CI) or `gh auth token` (local)."""
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok
    try:
        return subprocess.check_output(["gh", "auth", "token"], text=True).strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        sys.exit(f"No GITHUB_TOKEN/GH_TOKEN env and `gh auth token` failed: {exc}")


def graphql(token: str, variables: dict) -> dict:
    body = json.dumps({"query": QUERY, "variables": variables}).encode()
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=body,
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "vllm-force-merge-stats",
        },
    )
    with urllib.request.urlopen(req) as resp:
        payload = json.load(resp)
    if "errors" in payload:
        sys.exit(f"GraphQL errors: {payload['errors']}")
    return payload["data"]


def daterange_chunks(start: dt.date, end: dt.date, step_days: int = 7):
    """Yield (chunk_start, chunk_end) inclusive date pairs, non-overlapping."""
    cur = start
    while cur <= end:
        chunk_end = min(cur + dt.timedelta(days=step_days - 1), end)
        yield cur, chunk_end
        cur = chunk_end + dt.timedelta(days=1)


def fetch_window(token: str, start: dt.date, end: dt.date) -> dict:
    """Return {pr_number: record} for all PRs merged in [start, end]."""
    records: dict[int, dict] = {}
    for chunk_start, chunk_end in daterange_chunks(start, end):
        q = (
            f"repo:{REPO_OWNER}/{REPO_NAME} is:pr is:merged "
            f"merged:{chunk_start.isoformat()}..{chunk_end.isoformat()}"
        )
        cursor = None
        while True:
            data = graphql(token, {"q": q, "cursor": cursor})
            search = data["search"]
            for node in search["nodes"]:
                if not node:  # non-PR issue types come back empty
                    continue
                num = node["number"]
                merged_by = (node.get("mergedBy") or {}).get("login")
                records[num] = {
                    "number": num,
                    "title": node["title"],
                    "url": node["url"],
                    "mergedAt": node["mergedAt"],
                    "author": (node.get("author") or {}).get("login"),
                    "mergedBy": merged_by,
                    "force_merged": merged_by == FORCE_MERGE_LOGIN,
                }
            page = search["pageInfo"]
            if not page["hasNextPage"]:
                break
            cursor = page["endCursor"]
        print(
            f"  {chunk_start}..{chunk_end}: {search['issueCount']} merged",
            file=sys.stderr,
        )
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days", type=int, default=182, help="how many days back to fetch"
    )
    parser.add_argument("--out", default="data.json", help="output file")
    args = parser.parse_args()

    token = gh_token()
    today = dt.date.today()
    start = today - dt.timedelta(days=args.days)
    print(f"Fetching merged PRs {start}..{today} ...", file=sys.stderr)

    records = fetch_window(token, start, today)
    rows = sorted(records.values(), key=lambda r: r["mergedAt"], reverse=True)
    forced = sum(1 for r in rows if r["force_merged"])

    out = {
        "generated_at": dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "repo": f"{REPO_OWNER}/{REPO_NAME}",
        "force_merge_login": FORCE_MERGE_LOGIN,
        "window_start": start.isoformat(),
        "records": rows,
    }
    with open(args.out, "w") as f:
        json.dump(out, f, indent=1)

    pct = 100 * forced / len(rows) if rows else 0
    print(
        f"\nWrote {args.out}: {len(rows)} merged PRs, "
        f"{forced} force-merged ({pct:.1f}%) over {args.days} days.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
