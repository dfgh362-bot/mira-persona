# SPEC-v2 — MIRA build order (canon, frozen)

> Provenance note (D44): SPEC-v2.md and SPEC-v3.md are reconstructed from the
> ratified session canon (build orders as issued, decisions.jsonl R1–R8 /
> D9–D19, and the shipped v2 repository). SPEC-v3.1.md is verbatim. All three
> are frozen: the anti-drift check (v4) re-reads them every 50 cycles.

## 1. Objective

Build **MIRA**, a zero-cost AI-persona content automation system ("Mira Solis",
24, Lisbon barista / film photographer). All generation and hosting on free
tiers: Pollinations (images + text), GitHub Actions (scheduling + compute),
mail.tm (disposable inboxes), jsDelivr (CDN), GitHub Pages (site), Fanvue
(paid monetization). The persona is disclosed as AI everywhere, always.

## 2. Stack & defaults

- Repo `mira-persona`, branch `main`, UTC. Missing values → DEFAULTS in
  `scripts/util.py` (img_free_day 8, img_paid_day 4, video_day 2), logged (R8).
- Pure-stdlib Python scripts; `util.cli_guard` pattern: never crash the
  workflow — catch, log to state/log.jsonl, exit 0 (amended in v3.1 §0).
- Credentials: env (Actions Secrets) > config/accounts.json.

## 3. Persona & content

- Persona: warm neutral tones, film grain, oat cortados, Lisbon rooftops,
  35mm. 16 scenes + 20 captions at build (+ spare pools of +5/+5, refillable).
- Daily output quotas: 8 free + 4 paid images, 2 videos (ken-burns from 3
  stills, 720x1280 h264), voice notes via edge-tts (en-GB-SoniaNeural,
  rate -6%).
- Queue pipeline: generate → caption (Pollinations text, fallback captions) →
  post → archive. Item ids embed a seed to avoid cross-runner collisions (D33).

## 4. Publishing matrix

- Tier 1 auto: Bluesky, Telegram, Mastodon, Reddit, X, Pinterest.
- Tier 2 manual: TikTok, Instagram (API approval required).
- Tier 3 Playwright: Fanvue (manual until creds).
- Pricing: $9.99/mo subscription, $12.99 welcome bundle, $35 custom image,
  tips 5/10/25.

## 5. Disclosure (non-negotiable)

- Bio suffix every platform: " · ai-generated".
- Pinned first post (auto, D15): "i'm an ai-generated persona. mira isn't a
  real person — everything you see is generated. yes, the voice notes too."
- Fanvue AI-creator flag on. Captions never claim humanity, never deny AI.

## 6. Workflows (GitHub Actions)

- generate `0 6,18 * * *` (+ Pages deploy job, D14), post `0 9,13,17,21`,
  inbox `*/30`, keepalive `0 3`. Concurrency locks, 20-min timeouts,
  contents:write, commits route through the backlog engine (D31).

## 7. Files

4 workflows, config×4 (gh, accounts, platforms, schedule), prompts (scenes,
captions, spares), site/index.html, 15 scripts, state/ (ledger, log.jsonl,
decisions.jsonl).

## 8. Risks ratified (R1–R8)

Persona deception → disclosure strings; temp-mail breakage → retry ladder;
platform ToS → status:manual for forbidding platforms; mail.tm passwords
committed for disposable accounts only; PAT in .git/config accepted; Actions
as bot host accepted; missing values → DEFAULTS.

## 9. Decisions D9–D19 (build-time)

Sandbox path mapping (D9); GH_TOKEN blocked remote steps at build (D10);
platform signups need humans (D11); voice notes beyond spec tree (D12);
python 3.12 compatible (D13); Pages via workflow artifact (D14); pinned
disclosure auto-first (D15); mail.tm 503 deferred to runner (D16);
Pollinations 402 ladder (D17); build complete, remote deferred (D19).
