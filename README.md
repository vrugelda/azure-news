# azure-news

Pulls the Azure news feeds, keeps only the major updates that matter for architecture, summarises
them with Claude, and publishes the result as a static site on GitHub Pages.

There is no server. A scheduled GitHub Actions workflow runs the ingest, commits the refreshed
data to the repository, and deploys the `site/` folder.

## Publish on GitHub Pages

1. Push this folder to a GitHub repository with `main` as the default branch.
2. **Settings → Pages → Build and deployment → Source**: choose *GitHub Actions*.
3. **Settings → Secrets and variables → Actions**: add the secret `ANTHROPIC_API_KEY`.
4. Run the *Refresh and publish* workflow once from the Actions tab. After that it runs every six
   hours and whenever the site or code changes.

To change any setting from `.env.example` in the workflow, add it under `env:` in the
*Fetch and summarise* step of `.github/workflows/publish.yml`.

## Email notification

Optional. After each ingest, `azure-news notify` sends one email with the items that were
published for the first time, through [Azure Communication Services Email][acs]. Nothing is sent
when there is nothing new.

1. In Azure, create an *Email Communication Service* with a domain (the Azure-managed
   `azurecomm.net` domain is enough to start), create a *Communication Service*, and connect
   the domain to it under **Email → Domains**.
2. In the repository, under **Settings → Secrets and variables → Actions**, add:

   | Kind     | Name                               | Value                                               |
   | -------- | ---------------------------------- | --------------------------------------------------- |
   | Secret   | `AZURE_NEWS_ACS_CONNECTION_STRING` | Communication Service → **Keys** → connection string |
   | Secret   | `AZURE_NEWS_NOTIFY_TO`             | Recipients, comma-separated                         |
   | Variable | `AZURE_NEWS_NOTIFY_FROM`           | Sender, e.g. `DoNotReply@<guid>.azurecomm.net`      |
   | Variable | `AZURE_NEWS_NOTIFY_TIER`           | Optional: `all` to include the smaller updates      |
   | Variable | `AZURE_NEWS_SITE_URL`              | Optional: the Pages URL, linked from the email      |

All recipients are on the `To` line of the same message and can see each other's addresses.

Items waiting to be emailed are listed in `state/notifications.json`. If sending fails, the site
is still published, the workflow run is marked failed, and the items go out with the next run.
While notification is not configured the queue is emptied on every run, so turning it on later
does not send a backlog. Items that are only re-assessed (after a model or prompt change) are
not emailed again.

[acs]: https://learn.microsoft.com/azure/communication-services/concepts/email/email-overview

## Run it locally

Requires [uv](https://docs.astral.sh/uv/) (it fetches Python itself).

```sh
cp .env.example .env                          # add ANTHROPIC_API_KEY
uv run --env-file .env azure-news ingest      # writes site/data/news.json
python3 -m http.server 8000 -d site           # http://127.0.0.1:8000
```

To try it without an API key, run `AZURE_NEWS_SUMMARIZER=heuristic uv run azure-news ingest`.
Items are then picked by keyword rules, which are much looser than the real filter and write no
architecture impact. Don't commit the result: delete `site/data` and `state` afterwards.

## How it works

1. **Fetch** – Azure Updates, the Azure Blog and the Azure Architecture Blog (`feeds.py`).
2. **Assess** – items from the last 30 days that have not been assessed yet go to Claude in
   batches (`summarize.py`). Each gets an importance and an architecture-relevance score from 1 to
   5; a brief is written only for items at or above the thresholds (default 4 and 3). Architecture
   Blog posts are scored on how substantial the guidance is, and are kept for 120 days.
3. **Store** – kept items are written to `site/data/news.json`. The verdict for every item is kept
   in `state/assessments.json`, so an item is sent to the model again only if its text changes or
   the summariser changes.
4. **Notify** – items published for the first time are emailed (`notify.py`), if configured.
5. **Publish** – the frontend in `site/` is plain HTML, CSS and JavaScript that loads
   `data/news.json`. Architecture guidance is listed first. Items with architecture relevance 4
   or more are shown by default; the rest sit behind the "smaller updates" filter.

| Path                     | Committed | Contents                                         |
| ------------------------ | --------- | ------------------------------------------------ |
| `site/data/news.json`    | yes       | Published items, newest first                    |
| `state/assessments.json` | yes       | Score and verdict per feed item already assessed |
| `state/notifications.json` | yes     | Ids of published items not emailed yet           |
| `state/feeds/*.json`     | no        | Local cache of feed bodies, to avoid refetching  |

## Notes

- Each refresh commits `news.json` even when no items changed, because it records the refresh time.
- Only the first 6,000 characters of an item's text are sent for assessment (Architecture Blog
  posts embed the whole article).
- Summaries are generated and can be wrong; the page links every item to its source.

## Tests

```sh
uv run pytest
```
