# SIGNUP — the human's two minutes (v3.3)

One real Gmail address powers every platform identity via plus-addressing:

```
persona general   <base>+mirasolis@gmail.com
per platform      <base>+mirasolis-<platform>@gmail.com
```

Every WIRE issue: label it `command`, put the command in the title.
Values are redacted from the public issue on parse, secrets upload sealed-box,
the platform flips to ready, and the pinned disclosure post goes out FIRST
(`i'm an ai-generated persona. mira isn't a real person — everything you
see is generated. yes, the voice notes too.`) followed by the oldest
unposted item.

## Step 0 — store the base (once, ~1 minute)

1. Open `https://github.com/dfgh362-bot/mira-persona/settings/secrets/actions`
2. **New repository secret** — Name: `MAIL_BASE` — Value: your base gmail
   address (e.g. `you@gmail.com`)
3. Optional, if you want the loop to click confirmation links for you:
   enable IMAP in Gmail, create an App Password, and add three more secrets —
   `MAIL_IMAP_HOST=imap.gmail.com`, `MAIL_IMAP_USER=<base>`,
   `MAIL_IMAP_PASS=<app password>`. Without these, the human clicks the
   confirmation link (it is always the cheapest wall, ~1 min).

Cheapest-first order: **telegram → mastodon → reddit → x → pinterest → fanvue**.
bluesky: NEEDS PHONE, deferred (bottom).

## 1. telegram — 60 seconds, no email / phone / captcha

1. Open https://t.me/BotFather (needs your own Telegram login)
2. Send `/newbot` — name: `Mira Solis` — username: any free `..._bot`
3. Copy the token (`123456789:AA...`)
4. Create a public channel "Mira Solis" (bio ends with ` · ai-generated`),
   add the bot as **administrator**, post any message in it
5. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` — copy the
   `"chat":{"id":-100...}` number

WIRE block:

```
WIRE telegram
TELEGRAM_BOT_TOKEN=123456789:AA...
TELEGRAM_CHAT_ID=-1001234567890
```

## 2. mastodon — ~2 minutes

1. Sign up at https://mastodon.social/auth/sign_up with
   `<base>+mirasolis-mastodon@gmail.com` (display name "Mira Solis",
   bio with the ` · ai-generated` suffix)
2. Click the confirmation mail in your Gmail — or, before signing up, open
   the confirmation-only WIRE issue below and the loop watches the inbox
   (IMAP secrets) or reminds you it is the cheapest wall
3. Settings → Development → **New application** `mira-loop`, scopes:
   `read` + `write`
4. Copy the access token

Confirmation-only WIRE (before the token exists):

```
WIRE mastodon
EMAIL=<base>+mirasolis-mastodon@gmail.com
```

Full WIRE block:

```
WIRE mastodon
MASTODON_INSTANCE=https://mastodon.social
MASTODON_TOKEN=<access token>
```

## 3. reddit — ~4 minutes

1. Register at https://www.reddit.com/register with
   `<base>+mirasolis-reddit@gmail.com`
2. https://www.reddit.com/prefs/apps → **create another app** —
   name: `mira-loop`, type: **script**, redirect uri: `http://localhost:8080`
3. Copy the client id (under the app name) and the secret
4. Create (or pick) the subreddit to post in — bio/modlist with the
   disclosure suffix

WIRE block:

```
WIRE reddit
REDDIT_CLIENT_ID=<client id>
REDDIT_SECRET=<secret>
REDDIT_USERNAME=<username>
REDDIT_PASSWORD=<password>
REDDIT_SUBREDDIT=<subreddit name, no r/>
```

## 4. x — ~10 minutes (developer account)

1. https://developer.x.com — sign in with the platform X account
   (sign up via `<base>+mirasolis-x@gmail.com` first)
2. Apply for the free developer tier (email verification to the same address)
3. Create a Project + App → generate and copy the **Bearer Token**

WIRE block:

```
WIRE x
X_BEARER_TOKEN=<bearer token>
```

## 5. pinterest — ~5 minutes

1. Business account at https://www.pinterest.com with
   `<base>+mirasolis-pinterest@gmail.com`
2. Create a board (e.g. `mira · ai-generated`) — copy the board id
   (the number in the board URL)
3. https://developers.pinterest.com/apps/ — create an app, generate the
   access token

WIRE block:

```
WIRE pinterest
PINTEREST_TOKEN=<access token>
PINTEREST_BOARD_ID=<board id>
```

## 6. fanvue — ~8 minutes (monetization, tier 3)

1. Creator signup at https://fanvue.com with
   `<base>+mirasolis-fanvue@gmail.com`
2. Enable the **AI creator** flag in platform settings
3. Pricing: $9.99/mo, welcome pack $12.99, custom $35; tips 5/10/25
4. Bio carries the ` · ai-generated` suffix

WIRE block:

```
WIRE fanvue
FANVUE_EMAIL=<base>+mirasolis-fanvue@gmail.com
FANVUE_PASSWORD=<password>
```

## bluesky — NEEDS PHONE, deferred

bsky.social requires phone verification (v3.2 funnel-session finding; the
handle `itsmirasolis` was free at check time). Create the account in the
Bluesky **mobile app** with your own phone, then Settings → App passwords:

```
WIRE bluesky
BSKY_HANDLE=mirasolis.bsky.social
BSKY_APP_PASSWORD=<app password>
```

## rules the loop enforces (v3.3)

- **captcha budget, hard rule**: 2 programmatic attempts, then STOP — the
  wall goes to BLOCKERS.md + state/walls.jsonl with the exact URL, the wall
  type (`captcha|phone|email|queue`) and the 2-minute human step. Never a
  third chain. Non-captcha walls (phone/email/queue) skip the captcha
  entirely and go straight to BLOCKERS.
- **walls dashboard**: HANDOFF.md always shows exactly one line —
  `N platforms blocked | cheapest human unblock: <platform> (<est> min) -> <url>`
- **cycle report**: one line, no summary.
