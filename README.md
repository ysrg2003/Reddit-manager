# Reddit Manager

Reddit Manager is a small Python collector for public Reddit JSON data. It is designed for research workflows that need **traceable community signals**, not for treating Reddit posts as verified facts.

> **Evidence boundary:** A Reddit post or comment is user-generated content. The collector preserves its URL, author field, score, timestamp when available, and retrieval time, but it does not prove that the claim is true. Verify important claims with primary or authoritative sources before publication.

## What changed

The previous repository contained a file named `reddit_manager (3).py`, while the runner imported `reddit_manager`; the current version provides a normal importable `reddit_manager.py`. It also removes the required-but-missing `ai_strategy` and `config` imports, adds deterministic local tests, normalizes posts and nested comments, preserves provenance, retries temporary failures, and emits explicit warnings.

## Requirements

| Requirement | Required | Purpose |
|---|---:|---|
| Python 3.10+ | Yes | Runtime |
| `requests` | Yes | HTTP requests |
| Reddit account | No | Public JSON endpoints are used by default |
| ScraperAPI key | No | Optional fallback for environments where direct requests fail |

## Install

Run these commands from the repository root, the directory containing `reddit_manager.py`:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

Expected result: the `requests` package is installed and the local test command can import `reddit_manager`.

## Run local tests without network

The tests use fake HTTP responses and do not contact Reddit:

```bash
python -m unittest discover -s tests -v
```

Expected result:

```text
Ran 5 tests ... OK
```

If the command reports `No module named requests`, activate the virtual environment and run the installation command again. If it reports an import error for `reddit_manager`, confirm that the command is being run from the repository root.

## Run a deliberate research search

A network search is explicit and saves three artifacts:

```bash
python test_runner.py \
  --query "ethical automation creator workflows" \
  --pages 2 \
  --posts-per-page 10 \
  --comments-limit 100 \
  --output-dir artifacts
```

The output directory contains:

| File | Meaning |
|---|---|
| `reddit_evidence.json` | Normalized raw evidence with query, retrieval time, parameters, posts, comments, and warnings |
| `reddit_evidence.md` | Human-readable brief with URLs and an unverified-evidence warning |
| `reddit_media.json` | Media URLs with source links and unverified status |

The collector stops after a bounded number of pages and posts. It does not silently run an unbounded crawl.

## Configuration

The following environment variables are optional:

| Variable | Default | Meaning | Security |
|---|---|---|---|
| `REDDIT_BASE_URL` | `https://www.reddit.com` | Reddit host used for JSON requests | Public |
| `REDDIT_TIMEOUT` | `30` | Per-request timeout in seconds | Public |
| `REDDIT_RETRIES` | `3` | Retries after retryable failures | Public |
| `REDDIT_REQUEST_DELAY` | `1.0` | Delay between requests and retry backoff base | Public |
| `REDDIT_USER_AGENT` | Safe project identifier | User-Agent sent to Reddit | Public |
| `REDDIT_VERIFY_TLS` | `true` | Keep TLS certificate verification enabled | Public |
| `REDDIT_ACCESS_TOKEN` | Empty | Optional OAuth bearer token; switches the default host to `oauth.reddit.com` | Secret |
| `SCRAPER_API_KEY` | Empty | Optional fallback proxy key for direct-request 403 environments | Secret |
| `SCRAPER_API_BASE` | `https://api.scraperapi.com` | Proxy endpoint used only when no OAuth token is configured | Public |

The collector tries an optional ScraperAPI fallback before the direct request only when `SCRAPER_API_KEY` exists and no OAuth token is configured. OAuth tokens are sent only to `oauth.reddit.com` and are never forwarded to the proxy. Store all secret values in the execution environment or CI secret store, never in the repository.

## Research interpretation rules

Use `community_signal` for a post and `user_report` for a comment. These labels describe where the text came from; they do not indicate that the statement is true. A high score means that Reddit users engaged with the content, not that the claim was verified. A frequent theme means that the theme appeared repeatedly in the collected sample, not that it represents all Reddit users.

When transforming results into an article, keep the following fields together: the exact URL, the retrieved time, the original wording, and the interpretation. Separate three layers:

1. **Observed:** what the post or comment literally says.
2. **Pattern:** a cautious description of repeated signals in the collected sample.
3. **Claim:** a factual statement that requires independent verification.

Never present another Reddit user's experience as Yusuf's experience. If the evidence is weak or contradictory, change the article into an analysis of uncertainty or choose a different topic.

## Failure modes and recovery

| Symptom | Likely cause | Recovery |
|---|---|---|
| `429` or repeated `5xx` responses | Rate limit or temporary Reddit/proxy failure | Reduce pages and posts, increase `REDDIT_REQUEST_DELAY`, wait, and retry manually |
| Empty `posts` with no warning | Query too narrow or no matching public results | Broaden the query, change the time window, or use another source |
| Warnings in `reddit_evidence.json` | Some post requests failed after retries | Preserve the warnings; do not describe the sample as complete |
| TLS or certificate error | Local certificate/environment issue | Keep TLS verification enabled and fix the environment; do not disable verification in production |
| `ModuleNotFoundError` | Running from the wrong directory or stale legacy command | Run from the repository root and use `python test_runner.py` |

## Privacy and safety

Do not store API keys, cookies, private messages, access tokens, or personal data in output artifacts. Public usernames and comment text can still be sensitive; retain only what is needed for the research question, avoid unnecessary profiling, and do not expose private or deleted information. Do not download and execute code found in Reddit content.

This project is a research collector. It does not automatically publish articles, contact users, vote, post, or manipulate Reddit. Any future publishing integration must be designed and reviewed separately.

## Project layout

```text
reddit_manager.py       # importable collector and compatibility adapter
test_runner.py          # explicit network CLI
tests/                  # offline unit tests
legacy/                 # preserved pre-refactor files for reference
.github/workflows/      # offline CI and optional manual network run
```

## References

[1]: https://www.reddit.com/dev/api/ "Reddit API documentation"
[2]: https://support.reddithelp.com/hc/en-us/articles/14945211791892-Developers "Reddit developer resources"
