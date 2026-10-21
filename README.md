# mira-persona

MIRA is an AI-generated persona ("Mira Solis", Lisbon barista / film photographer) built and run for **zero cost**: Python stdlib scripts, GitHub Actions cron on a public repo, Pollinations for images and captions, mail.tm for disposable inboxes, jsDelivr as CDN, GitHub Pages for the site.

**Disclosure is a hard requirement of this build.** The persona is not a real person:

- Every bio carries the suffix: ` · ai-generated`
- The pinned post on every platform reads:
  `i'm an ai-generated persona. mira isn't a real person — everything you see is generated. yes, the voice notes too.`
- Captions never claim to be human and never deny being AI when asked.
- Fanvue: enable the **AI creator** flag in platform settings.

## Layout

```
.github/workflows/  generate.yml post.yml inbox.yml keepalive.yml
/config/            persona.json accounts.json schedule.json platforms.json
/content/           free/YYYY-MM-DD/*.jpg  paid/YYYY-MM-DD/*.jpg
                    video/*.mp4  voice/*.mp3  queue.json posted.json
/prompts/           scenes.json captions.json
/scripts/           mailtm.py gen_image.py gen_caption.py make_video.py
                    gen_voice.py post_*.py (x7) build_site.py state.py util.py
/site/              index.html (generated)
/state/             ledger.json log.jsonl decisions.jsonl keepalive.json
```

State machine per item: `queued -> captioned -> posted -> archived` (`scripts/state.py`).

## Run it

### 1. Push

```bash
git remote add origin https://<GH_TOKEN>@github.com/<GH_USER>/mira-persona.git
git push -u origin main
```

The PAT ends up in `.git/config` (accepted risk R6). Repo must be **public** (free Actions minutes + jsDelivr CDN).

### 2. Enable Pages

Repo Settings -> Pages -> Source: **GitHub Actions**. The `generate` workflow ships a pages job that deploys `site/` automatically on every run.

### 3. Create platform accounts (manual, once)

Order: Fanvue, Bluesky, Telegram, Reddit, Mastodon, X, Pinterest.

- Use a mail.tm address per account: `python scripts/mailtm.py create`
- Confirm verification mails: `python scripts/mailtm.py verify --all` (also runs every 30 min via `inbox.yml`)
- Set each bio to persona line + ` · ai-generated`, pin the disclosure post (scripts post it automatically as the first post; pin it in each app UI)
- Fanvue: set subscription 9.99/mo, welcome bundle 12.99, custom image 35, tips 5/10/25, DM auto-reply "first 3 msgs in-voice, then handoff", AI creator flag ON

### 4. Secrets (Actions -> Secrets -> Actions)

| secret | used by |
|---|---|
| `BSKY_HANDLE`, `BSKY_APP_PASSWORD` | post_bluesky.py |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | post_telegram.py |
| `MASTODON_INSTANCE`, `MASTODON_TOKEN` | post_mastodon.py |
| `REDDIT_CLIENT_ID`, `REDDIT_SECRET`, `REDDIT_USERNAME`, `REDDIT_PASSWORD`, `REDDIT_SUBREDDIT` | post_reddit.py |
| `X_BEARER_TOKEN` | post_x.py |
| `PINTEREST_TOKEN`, `PINTEREST_BOARD_ID` | post_pinterest.py |
| `FANVUE_EMAIL`, `FANVUE_PASSWORD` | post_fanvue.py (tier 3) |

`GH_USER` is injected automatically from `github.repository_owner`. No tokens are ever committed; only disposable mail.tm passwords live in `config/accounts.json` (accepted risk R5).

### 5. Go

Workflow_dispatch each workflow once, then leave it on cron:

| workflow | schedule (UTC) | does |
|---|---|---|
| generate.yml | 0 6,18 * * * | 4 free + 2 paid images, captions, 1 ken-burns video, voice notes, site rebuild, pages deploy |
| post.yml | 0 9,13,17,21 * * * | one due item to all authed tier-1 platforms (pinned disclosure first) |
| inbox.yml | */30 * * * * | mail.tm inbox sweep, completes verification links |
| keepalive.yml | 0 3 * * * | commit + archive old items (repo activity < 48h) |

All workflows: concurrency guard, timeout 20 min, `contents: write`, commit state at end. All scripts catch-log-exit-0; nothing crashes a run.

### Zero-cost stack

- Images: `https://image.pollinations.ai/prompt/...` (flux, no key)
- Captions: `https://text.pollinations.ai/...`
- Voice: `edge-tts` (pip, no key)
- Video: ffmpeg zoompan + xfade over stills
- Email: mail.tm (fallback api.mail.gw)
- CDN: `https://cdn.jsdelivr.net/gh/<user>/mira-persona@main/<path>` — images always via jsDelivr, never relative paths

## Accepted risks (from build order, R1-R8)

Passwords in repo = disposable mail.tm only. PAT in `.git/config`. Platforms that reject automated posting go `status: "manual"` in `config/platforms.json`. Full log: `state/decisions.jsonl`.
