# STOCK WARS

## Deploy on Railway
1. Push this folder to a GitHub repo → Railway → **New Project → Deploy from GitHub**. It builds from `Dockerfile` (`railway.json` included).
2. In the same project add **PostgreSQL** and **Redis** (+ New → Database).
3. App service → **Variables**:
   - `BOT_TOKEN` = token from @BotFather
   - `OWNER_IDS` = your Telegram user ID (auto-admin)
   - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}`
   - `REDIS_URL` = `${{Redis.REDIS_URL}}`
   - `WEBAPP_URL` = your public URL (step 4)
   - optional: `NEWS_CHANNEL_ID` (bot must be channel admin), `IPO_REQUIRES_APPROVAL=1`, `IPO_MIN_AGE_HOURS=0` for testing
4. App service → **Settings → Networking → Generate Domain**, paste it into `WEBAPP_URL`, redeploy.
5. Keep **1 replica** (bot uses polling). Tables are created automatically on first boot (`AUTO_CREATE_TABLES=1`).
6. Open the bot → /start. Owner is auto-approved; others /register → you /approve <id>.

## Local
`cp .env.example .env` → `docker compose up --build`

## Bot commands
Players: /start /register /profile /market /stocks /stock /buy /sell /portfolio /history /news /leaderboard /mycompany /ipos /loan /repay /dividends
Admin: /pending /approve /reject /suspend /unsuspend /ban /unban /playerinfo /addcash /removecash /marketpause /marketresume /forceevent <key> /stop_event <id> /approveipo <id> /rejectipo <id> /audit
