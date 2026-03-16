# AI Chance Bot — Railway Deployment Guide

Railway is the simplest option — no CLI needed, deploy straight from GitHub.

---

## Step 1 — Create GitHub Repository

1. Go to github.com → sign in or create account
2. Click New repository → name it ai-chance-bot → Private → Create
3. Upload these 4 files:
   - server.py
   - requirements.txt
   - railway.json
   - Dockerfile

Easiest: click Add file → Upload files → drag and drop → Commit changes

---

## Step 2 — Create Railway Account

1. Go to railway.app
2. Click Login with GitHub
3. Free tier = $5 credit/month — plenty for trading alerts

---

## Step 3 — Deploy

1. Railway dashboard → New Project → Deploy from GitHub repo
2. Select ai-chance-bot
3. Railway auto-detects Python and builds automatically

---

## Step 4 — Set Environment Variables

Service → Variables tab → Add Variable:

  ANTHROPIC_API_KEY   = sk-ant-...
  TELEGRAM_BOT_TOKEN  = 7123456789:AAFxxx...
  TELEGRAM_CHAT_ID    = 123456789
  PORT                = 8080

Click Deploy after adding — Railway redeploys automatically.

---

## Step 5 — Get Your Webhook URL

Service → Settings → Networking → Generate Domain

Your URL: https://ai-chance-bot-production-xxxx.up.railway.app
Webhook:  https://ai-chance-bot-production-xxxx.up.railway.app/webhook

---

## Step 6 — Test Health Check

Open browser: https://ai-chance-bot-production-xxxx.up.railway.app/health
Should show: {"status": "ok", "version": "1.2"}

---

## Step 7 — Set Up TradingView Alerts

For each of the 6 signals (TMN+, TMN-, BUY, SELL, TMN+ Watch, TMN- Watch):

1. TradingView → Alert → Create Alert
2. Condition: AI Chance v1.2 → select signal
3. Webhook URL: your Railway URL + /webhook
4. Message: paste matching JSON from alert_templates.py
5. Create

---

## Monitoring

Railway dashboard → service → Logs tab
Shows every webhook and Telegram message in real time.

---

## Updating

Edit files in GitHub → Railway auto-redeploys in ~1 minute.
