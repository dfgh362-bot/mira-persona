# BACKLOG — infinite queue (never empty)

- [ ] T-0006 | create first mail.tm account | onboarding | cmd: python scripts/mailtm.py create
- [ ] T-0007 | rebuild site | pipeline | cmd: python scripts/build_site.py
- [ ] T-0008 | sweep mail.tm inboxes | verification | cmd: python scripts/mailtm.py verify --all
- [ ] T-0009 | archive old items | hygiene | cmd: python scripts/state.py archive --older-than 48h
- [ ] T-0010 | onboard fanvue: AI creator flag + pricing 9.99/12.99/35 + tips 5/10/25 + DM auto-reply | onboarding (human)
- [ ] T-0011 | onboard bluesky: account + app password, set as Actions Secrets | onboarding (human)
- [ ] T-0012 | onboard telegram: bot via BotFather, token + chat id | onboarding (human)
- [ ] T-0013 | onboard reddit: script app OAuth, sub + creds | onboarding (human)
- [ ] T-0014 | onboard mastodon: account + app token | onboarding (human)
- [ ] T-0015 | onboard x: developer account + bearer token | onboarding (human)
- [ ] T-0016 | onboard pinterest: account + board + token | onboarding (human)
- [x] T-0005 | generate 2 paid images | ok: quota met (4/4 paid images today), skipping | cmd: python scripts/gen_image.py --tier paid --count 2
- [x] T-0004 | generate 3 free images | ok: quota met (9/8 free images today), skipping | cmd: python scripts/gen_image.py --tier free --count 3
- [x] T-0003 | caption queued items | ok: captioned 0 item(s) | cmd: python scripts/gen_caption.py
- [x] T-0001 | finish v2: remote bring-up (repo, push, Pages, topics, dispatch all) | ok: bringup complete: https://github.com/dfgh362-bot/mira-person | cmd: python scripts/bringup_remote.py
- [x] T-0002 | build 1 video clip | ok: built content/video/mira_clip_20261021_02.mp4 from 3 stills
