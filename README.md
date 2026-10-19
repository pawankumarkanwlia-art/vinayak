# Sarkari Job Telegram Alert Bot

Checks SarkariResult.com.cm and FreeJobAlert.com on a GitHub Actions schedule and sends newly discovered job-related pages to a Telegram channel.

## Files
- `job_bot.py`: site discovery, basic details extraction, Telegram sending, deduplication.
- `requirements.txt`: Python dependencies.
- `.github/workflows/job-alert.yml`: runs every 15 minutes and can also be started manually.
- `seen_jobs.json`: persistent URL history used to avoid repeat alerts.

## Setup
1. Create a Telegram bot with `@BotFather` and copy its token.
2. Add the bot to your channel as an administrator with permission to post messages.
3. For a public channel, set `TELEGRAM_CHAT_ID` to `@YourChannelUsername`. For a private channel, use its numeric chat ID (often starts with `-100`).
4. Create a GitHub repository and upload these files to its default branch.
5. In GitHub, open **Settings → Secrets and variables → Actions → New repository secret** and add:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
6. Open **Settings → Actions → General → Workflow permissions** and allow read/write permissions if your repository settings require it.
7. Open **Actions → Sarkari Job Telegram Alerts → Run workflow** to test immediately. The scheduled workflow runs every 15 minutes after that.

## Important limitations
- This is a best-effort HTML/sitemap scanner, not an official integration. Website structure and anti-bot policies can change.
- Qualification and deadline text is extracted heuristically; if not found, the message explicitly says it is unavailable. Always verify the source notification.
- The first run may identify already-existing pages as new because the bot starts with an empty `seen_jobs.json`. Review the first test run and channel before relying on it.
- Scheduled GitHub Actions may be delayed. In public repositories, scheduled workflows can be disabled after 60 days without repository activity.
- Be respectful of each site's terms and robots.txt. If a site blocks automated requests or disallows this use, remove it or use an authorized feed/API instead.
- Keep bot tokens in GitHub Secrets. Never commit them to the repository.
