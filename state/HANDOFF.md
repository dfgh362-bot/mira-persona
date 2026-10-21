## CURRENT
T-0034 selftest v32: wire channel, lint, funnel-first, name contract — -- 20/20 passed
## NEXT ACTION
python scripts/backlog.py --one  # T-0011 (needs human)
## BLOCKERS
- WIRE bluesky: onboarding needs human — secrets expected: BSKY_HANDLE, BSKY_APP_PASSWORD (or body lines KEY=value in a 'WIRE bluesky' issue, label: command) (ts 2026-10-22T00:00:00Z)
- WIRE telegram: onboarding needs human — secrets expected: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (or body lines KEY=value in a 'WIRE telegram' issue, label: command) (ts 2026-10-22T00:00:00Z)
- WIRE reddit: onboarding needs human — secrets expected: REDDIT_CLIENT_ID, REDDIT_SECRET, REDDIT_USERNAME, REDDIT_PASSWORD, REDDIT_SUBREDDIT (or body lines KEY=value in a 'WIRE reddit' issue, label: command) (ts 2026-10-22T00:00:00Z)
- WIRE mastodon: onboarding needs human — secrets expected: MASTODON_INSTANCE, MASTODON_TOKEN (or body lines KEY=value in a 'WIRE mastodon' issue, label: command) (ts 2026-10-22T00:00:00Z)
- WIRE x: onboarding needs human — secrets expected: X_BEARER_TOKEN (or body lines KEY=value in a 'WIRE x' issue, label: command) (ts 2026-10-22T00:00:00Z)
- WIRE pinterest: onboarding needs human — secrets expected: PINTEREST_TOKEN, PINTEREST_BOARD_ID (or body lines KEY=value in a 'WIRE pinterest' issue, label: command) (ts 2026-10-22T00:00:00Z)
- WIRE fanvue: onboarding needs human — secrets expected: FANVUE_EMAIL, FANVUE_PASSWORD (or body lines KEY=value in a 'WIRE fanvue' issue, label: command) (ts 2026-10-22T00:00:00Z)
- T-0010 needs human: onboard fanvue: AI creator flag + pricing 9.99/12.99/35 + tips 5/10/25 + DM auto-reply (ts 2026-10-21T18:47:33Z)
- WIRE needs GH_PAT: secret uploads require a token with secrets access (GITHUB_TOKEN cannot write secrets) — store a PAT (repo scope) once as Actions secret GH_PAT, or run scripts/issues.py --poll locally (ts 2026-10-22T00:00:00Z)
## LAST COMMIT
3c278b5
## CYCLE
23
