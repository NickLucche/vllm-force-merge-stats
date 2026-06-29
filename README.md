# vLLM Force-Merge Stats

A tiny static dashboard showing how often pull requests in
[vllm-project/vllm](https://github.com/vllm-project/vllm) are **force-merged**.

**🔗 Live dashboard: https://nicklucche.github.io/vllm-force-merge-stats/**

## What is a "force-merge"?

A force-merge is a merge performed by the **`vllm-bot`** account. Lead maintainers
use it to override CI when a failure is unrelated to the PR (see the
[vLLM governance docs](https://docs.vllm.ai/en/latest/governance/process/)).

## How detection works

For each merged PR we query the GitHub GraphQL API and read a single field —
the login of the account that performed the merge:

```graphql
... on PullRequest { number mergedAt author { login } mergedBy { login } }
```

A PR is counted as force-merged when **`mergedBy.login == "vllm-bot"`**.
`fetch.py` runs this query over a date range (chunked by week to stay under the
search API's 1000-results cap) and writes one record per PR to `data.json`.

### Why this is the right signal

- **Git history can't detect it.** Every PR is squash-merged with committer
  `GitHub <noreply@github.com>`. A force-merged commit is byte-for-byte
  indistinguishable from a normal one. Detection must use the GitHub API.
- **`vllm-bot` is exclusively the force-merge executor.** In a sample of recent
  merges, every `vllm-bot` merge had non-green CI at merge time, while normal
  merges show the human maintainer's login. Zero false positives.
- It comes **free** in a single GraphQL query — no per-PR API calls.

### This is a lower bound

The count reflects merges routed through `vllm-bot`, which is the *standard*
force-merge path. It will **under**-count any force-merge done a different way:

- A repo admin clicking "Merge" with failing/pending checks (GitHub's admin
  override) — that records the **human** maintainer as `mergedBy`, not `vllm-bot`.
  In a recent sample ~11 human merges also had non-green CI; these are excluded.
- Branch-protection settings changed momentarily to allow a manual merge.

So treat the reported percentage as a **floor** on the true force-merge rate.
A broader "any CI-bypassing merge" metric would additionally need each PR's CI
rollup state at merge time (`statusCheckRollup`), at extra API cost.

## Files

| File | Purpose |
|------|---------|
| `fetch.py` | Fetches merged PRs via the GitHub GraphQL API, flags force-merges, writes `data.json`. Stdlib only. |
| `data.json` | Generated dataset (one record per merged PR). |
| `index.html` | Static dashboard; computes the time-window stats in the browser. |

## Automated updates

A GitHub Action ([`.github/workflows/update-data.yml`](.github/workflows/update-data.yml))
refreshes `data.json` **daily at 06:17 UTC** and commits it back to `main`, which
republishes the Pages site automatically. It uses the built-in `GITHUB_TOKEN` —
no secrets to configure. You can also trigger it on demand from the repo's
**Actions** tab → *Update force-merge data* → *Run workflow*.

> **Note:** GitHub disables scheduled workflows after 60 days of repo inactivity.
> Any manual run or commit re-arms the schedule.

## Refreshing the data manually

Requires the [GitHub CLI](https://cli.github.com/) logged in (`gh auth login`) —
the script reads your token via `gh auth token` (or a `GITHUB_TOKEN`/`GH_TOKEN`
env var), so no token handling is needed.

```bash
python3 fetch.py            # last 182 days (~6 months), the default
python3 fetch.py --days 365 # custom window
```

This rewrites `data.json`. Commit it to publish the update.

## Viewing locally

`index.html` fetches `data.json`, so it must be served over HTTP (not `file://`):

```bash
python3 -m http.server 8000
# open http://localhost:8000
```

## Publishing on GitHub Pages

1. Create a new GitHub repo and push these files (including `data.json`).
2. In the repo: **Settings → Pages → Build and deployment → Source: Deploy from a branch**,
   pick `main` / `(root)`, save.
3. The dashboard will be live at `https://<you>.github.io/<repo>/`.

To refresh published stats, re-run `python3 fetch.py` and commit the new `data.json`.
