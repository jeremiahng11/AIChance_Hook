"""
AI Chance v1.2 — Webhook Server
Receives TradingView alerts → enriches with Claude AI → sends to Telegram

Setup:
  pip install flask anthropic python-telegram-bot requests
  Set environment variables:
    ANTHROPIC_API_KEY=your_key
    TELEGRAM_BOT_TOKEN=your_bot_token
    TELEGRAM_CHAT_ID=your_chat_id
  Run: python server.py
  Expose publicly: ngrok http 5000  (or deploy to server)
  Use the public URL as TradingView webhook: https://xxxx.ngrok.io/webhook
"""

import os
import json
import logging
from datetime import datetime
from flask import Flask, request, jsonify
import anthropic
import requests

# ── CONFIG ────────────────────────────────────────────────
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
PORT               = int(os.environ.get("PORT", 5000))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── SIGNAL EMOJI MAP ──────────────────────────────────────
SIGNAL_EMOJI = {
    "TMN+":        "⚡🟢",
    "TMN-":        "⚡🔴",
    "BUY":         "✅🟢",
    "SELL":        "✅🔴",
    "TMN+ Watch":  "👀🟢",
    "TMN- Watch":  "👀🔴",
}

# ── CLAUDE ANALYSIS ───────────────────────────────────────
def analyse_signal(payload: dict) -> str:
    """Send signal context to Claude and get full analysis with confidence score."""

    symbol      = payload.get("symbol", "UNKNOWN")
    signal      = payload.get("signal", "UNKNOWN")
    price       = payload.get("price", 0)
    bias        = payload.get("bias", "UNKNOWN")
    bias_score  = payload.get("bias_score", 0)
    htf         = payload.get("htf", "UNKNOWN")
    a5_dist     = payload.get("a5_dist", 0)
    stmn        = payload.get("stmn", 0)
    atr         = payload.get("atr", 0)
    tma_lower   = payload.get("tma_lower", 0)
    tma_upper   = payload.get("tma_upper", 0)
    tma_middle  = payload.get("tma_middle", 0)
    buy_thresh  = payload.get("buy_thresh", 0)
    sell_thresh = payload.get("sell_thresh", 0)
    rsi         = payload.get("rsi", 0)
    tl_score    = payload.get("tl_score", None)
    timeframe   = payload.get("timeframe", "5m")
    sym_mode    = payload.get("sym_mode", "Metals")

    direction = "BULLISH" if "+" in signal or signal == "BUY" else "BEARISH"
    zone = ("ABOVE SELL THRESHOLD" if price >= sell_thresh
            else "BELOW BUY THRESHOLD" if price <= buy_thresh
            else "NEUTRAL ZONE")

    prompt = f"""You are an expert trading analyst specialising in {sym_mode} ({symbol}) on a {timeframe} chart.

A trading signal has just fired from the AI Chance v1.2 indicator (based on TAD Market Navigator logic).

SIGNAL DATA:
- Signal: {signal} ({direction})
- Price: {price}
- ATR(14): {atr}
- RSI(14): {rsi}

BIAS & TREND:
- Bias Direction: {bias}
- Bias Score (net): {bias_score} (scale: -8 to +8, ≥2 = bull, ≤-2 = bear)
- HTF Status: {htf}
- A5 Distance: {a5_dist}x ATR from A5 (TMA middle)
- STMN Active: {"YES" if stmn else "NO"}

TAD LEVELS:
- TMA Lower: {tma_lower}  |  TMA Middle: {tma_middle}  |  TMA Upper: {tma_upper}
- Buy Threshold: {buy_thresh}  |  Sell Threshold: {sell_thresh}
- Price Zone: {zone}
{f"- TL Ready Score: {tl_score} (0 = price at target, negative = above target, positive = approaching)" if tl_score is not None else ""}

Provide a concise trading analysis in this EXACT format:

📊 SIGNAL ANALYSIS
Signal quality: [STRONG / MODERATE / WEAK] — [one line reason]

📈 MARKET CONTEXT
[2-3 sentences covering bias, trend, extension, any warnings]

🎯 TRADE SETUP
Direction: [BUY / SELL / WAIT]
Entry zone: [price level or range]
Stop Loss: [price level] ([X pts away])
Take Profit 1: [price level] ([X pts away])
Take Profit 2: [price level] ([X pts away])
R:R Ratio: [X:1]

⚠️ KEY RISKS
[2 bullet points of main risks]

🔢 CONFIDENCE SCORE: [0–100]%
[One sentence explaining the score]

Keep the entire response under 300 words. Be direct and specific with price levels."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text
    except Exception as e:
        log.error(f"Claude API error: {e}")
        return f"⚠️ AI analysis unavailable: {str(e)}"


# ── TELEGRAM SENDER ───────────────────────────────────────
def send_telegram(message: str) -> bool:
    """Send message to Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram credentials not set")
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }, timeout=10)
        if resp.status_code == 200:
            log.info("Telegram message sent ✓")
            return True
        else:
            log.error(f"Telegram error: {resp.text}")
            return False
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        return False


# ── FORMAT ALERT MESSAGE ──────────────────────────────────
def format_alert(payload: dict, analysis: str) -> str:
    """Format the full Telegram message."""
    signal   = payload.get("signal", "UNKNOWN")
    symbol   = payload.get("symbol", "UNKNOWN")
    price    = payload.get("price", 0)
    timeframe= payload.get("timeframe", "5m")
    emoji    = SIGNAL_EMOJI.get(signal, "🔔")
    ts       = datetime.utcnow().strftime("%H:%M UTC")

    header = (
        f"{emoji} <b>AI Chance v1.2 — {signal}</b>\n"
        f"<b>{symbol}</b> · {timeframe} · {price} · {ts}\n"
        f"{'─'*32}\n\n"
    )
    return header + analysis


# ── WEBHOOK ENDPOINT ──────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        payload = request.get_json(force=True)
        if not payload:
            return jsonify({"error": "empty payload"}), 400

        signal = payload.get("signal", "")
        log.info(f"Signal received: {signal} on {payload.get('symbol')} @ {payload.get('price')}")

        # Only process configured signals
        allowed = ["TMN+", "TMN-", "BUY", "SELL", "TMN+ Watch", "TMN- Watch"]
        if signal not in allowed:
            return jsonify({"status": "ignored", "signal": signal}), 200

        # Get AI analysis
        analysis = analyse_signal(payload)

        # Format and send
        message = format_alert(payload, analysis)
        sent = send_telegram(message)

        return jsonify({"status": "sent" if sent else "analysis_only", "signal": signal}), 200

    except Exception as e:
        log.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "version": "1.2"}), 200


if __name__ == "__main__":
    log.info(f"AI Chance Bot starting on port {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
