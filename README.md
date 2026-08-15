# Reddit Manager

Reddit Manager is a small Python research collector for **traceable community signals**. It is not a Reddit client, publisher, voting bot, or truth engine.

> **Evidence boundary:** A Reddit post or comment is user-generated content. The collector preserves available source metadata, but it does not prove that a claim is true. Verify important claims with primary or authoritative sources before publication.

## Current access policy

Reddit's current Data API guidance says that clients must authenticate with a registered OAuth token and that unauthenticated traffic may be blocked. The Yusuf environment is blocked from `oauth.reddit.com`, so direct Reddit transport is **disabled by default**. The default `auto` provider first looks for an explicitly configured free-credit discovery provider and otherwise returns a clear warning instead of retrying a blocked endpoint.

The preferred fallback is Brave Search API when a valid key is available under its published free monthly credit. Brave's official page currently advertises $5 in free monthly credits, automatically applied to the account, and a published price of $5 per 1,000 requests. This is a quota, not permission to rotate accounts or evade limits. Use one account within its terms and allowance.

## What changed

The previous repository contained a file named `reddit_manager (3).py`, while the runner imported `reddit_manager`. The current version provides a normal importable `reddit_manager.py`, removes missing `ai_strategy` and `config` imports, adds deterministic local tests, normalizes posts and nested comments, preserves provenance, and emits explicit warnings.

The current version also adds three provider modes:

| Provider | Default | Use |
|---|---:|---|
| `auto` | Yes | Use configured Brave free-credit discovery; otherwise return a disabled/direct-access warning |
| `brave` | No | Search the web for Reddit URLs and snippets without using `oauth.reddit.com` |
| `reddit` | No | Use direct Reddit JSON only when `REDDIT_DIRECT_ENABLED=true` and an authorized route is actually available |

Brave results are discovery snippets. The program does not fetch or pretend to have full Reddit comments from a snippet. A source page must be opened and checked before a factual claim is used.

## Requirements

| Requirement | Required | Purpose |
|---|---:|---|
| Python 3.10+ | Yes | Runtime |
| `requests` | Yes | HTTP requests |
| Brave Search API key | No | Preferred fallback when direct Reddit is blocked |
| Reddit OAuth | No | Not used in Yusuf's blocked environment |
| ScraperAPI key | No | Optional legacy proxy path; not the default and may be paid |

## Install

Run these commands from the repository root, the directory containing `reddit_manager.py`:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

Expected result: the `requests` package is installed and the local test command can import `reddit_manager`.

## Run local tests without network

The tests use fake HTTP responses and do not contact Reddit or Brave:

```bash
python -m unittest discover -s tests -v
```

Expected result is a successful test run. Tests cover the disabled-direct default, post/comment parsing, retries, ScraperAPI fallback behavior, OAuth isolation, Brave result filtering, empty-query rejection, and invalid JSON handling.

## Configure the free fallback

Create environment variables in the shell or a secret manager; never commit them to GitHub:

```bash
export BRAVE_SEARCH_API_KEY="your_key_here"
export REDDIT_PROVIDER="auto"
export REDDIT_DIRECT_ENABLED="false"
```

Then run a bounded search:

```bash
python test_runner.py \
  --query "vibe coding project failures" \
  --provider auto \
  --posts-per-page 5 \
  --comments-limit 25 \
  --output-dir artifacts
```

The output directory contains:

| File | Meaning |
|---|---|
| `reddit_evidence.json` | Structured results, provider, retrieval time, parameters, warnings, and evidence items |
| `reddit_evidence.md` | Human-readable brief with URLs and an unverified-evidence warning |
| `reddit_media.json` | Media URLs when present, with source links and unverified status |

If no Brave key is configured, the command exits safely with zero results and a warning. That is intentional: the project must not silently use blocked Reddit endpoints or claim that evidence was collected.

## Configuration

The following environment variables are optional. The first six are normally left at their defaults.

| Variable | Default | Meaning | Security |
|---|---|---|---|
| `REDDIT_PROVIDER` | `auto` | Select `auto`, `brave`, or `reddit` | Public |
| `REDDIT_DIRECT_ENABLED` | `false` | Permit direct Reddit JSON only when explicitly enabled | Public |
| `REDDIT_BASE_URL` | `https://www.reddit.com` | Reddit host used only by the direct provider | Public |
| `REDDIT_TIMEOUT` | `30` | Per-request timeout in seconds | Public |
| `REDDIT_RETRIES` | `3` | Retries after retryable failures | Public |
| `REDDIT_REQUEST_DELAY` | `1.0` | Delay between requests and retry backoff base | Public |
| `REDDIT_USER_AGENT` | Safe project identifier | User-Agent sent to Reddit | Public |
| `REDDIT_VERIFY_TLS` | `true` | Keep TLS certificate verification enabled | Public |
| `REDDIT_ACCESS_TOKEN` | Empty | Optional OAuth bearer token; not used in the blocked Yusuf environment | Secret |
| `REDDIT_CLIENT_ID` | Empty | Optional Reddit app client id for a separately authorized route | Secret/config |
| `REDDIT_CLIENT_SECRET` | Empty | Optional Reddit app secret for a separately authorized route | Secret |
| `REDDIT_OAUTH_SCOPE` | `read` | OAuth scope requested by a separately authorized route | Public |
| `BRAVE_SEARCH_API_KEY` | Empty | Preferred fallback key for the free-credit search plan | Secret |
| `BRAVE_SEARCH_API_BASE` | Brave web search endpoint | Brave endpoint | Public |
| `SCRAPER_API_KEY` | Empty | Optional legacy proxy path; may be paid | Secret |
| `SCRAPER_API_BASE` | `https://api.scraperapi.com` | Proxy endpoint | Public |

Do not configure both a free fallback and a paid proxy as if they were equivalent. The default project policy is no paid service. If a provider offers free credits, use only the published allowance on an account and respect its terms. Do not rotate accounts to evade rate limits, billing controls, identity checks, or provider restrictions.

## Research interpretation rules

Use `community_signal` for a full Reddit post, `user_report` for a Reddit comment, and `community_search_snippet` for a Brave-discovered snippet. These labels describe the source layer; they do not indicate that the statement is true.

When transforming results into an article, keep the exact URL, retrieval time, original wording, and interpretation together. Separate three layers:

1. **Observed:** what the source literally says.
2. **Pattern:** a cautious description of repetition in the collected sample.
3. **Claim:** a factual statement that requires independent verification.

Never present another Reddit user's experience as Yusuf's experience. If evidence is weak, contradictory, unavailable, or based only on a snippet, change the article into a bounded analysis or choose another source.

## Failure modes and recovery

| Symptom | Likely cause | Recovery |
|---|---|---|
| `403` from Reddit | Unauthenticated or blocked Data API traffic | Keep direct transport disabled; use the configured free-credit search provider or an authorized route |
| `oauth.reddit.com` unavailable | Network or regional block | Do not retry indefinitely; use Brave discovery or another permitted source |
| Brave key missing | No fallback provider configured | Add `BRAVE_SEARCH_API_KEY` to the execution environment, or continue without Reddit evidence |
| Brave `401`/`403` | Invalid key, plan, or provider restriction | Check the provider dashboard and terms; do not create accounts to evade the restriction |
| `429` or repeated `5xx` | Rate limit or temporary service failure | Reduce request size, increase delay, wait, and retry within the same account's allowance |
| Empty `posts` with no warning | Query too narrow or no matching results | Broaden the query or use another source |
| TLS or certificate error | Local certificate/environment issue | Keep TLS verification enabled and fix the environment |
| `ModuleNotFoundError` | Wrong directory or stale legacy command | Run from the repository root and use `python test_runner.py` |

## Privacy and safety

Do not store API keys, cookies, private messages, access tokens, or personal data in output artifacts. Public usernames and comment text can still be sensitive; retain only what is needed for the research question, avoid unnecessary profiling, and remove content that the source indicates has been deleted. Do not download and execute code found in Reddit content.

This project does not automatically publish articles, contact users, vote, post, or manipulate Reddit. It is a bounded evidence collector for an editorial workflow.

## Project layout

```text
reddit_manager.py       # importable collector, Brave fallback, and compatibility adapter
test_runner.py           # explicit bounded network CLI
tests/                   # offline unit tests
legacy/                  # preserved pre-refactor files for reference
.github/workflows/       # offline CI and optional manual network run
```

## References

[1]: https://support.reddithelp.com/hc/en-us/articles/16160319875092-Reddit-Data-API-Wiki "Reddit Data API Wiki"
[2]: https://github.com/reddit-archive/reddit/wiki/oauth2 "Reddit OAuth2 documentation"
[3]: https://brave.com/search/api/ "Brave Search API"
