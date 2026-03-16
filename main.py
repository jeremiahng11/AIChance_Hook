import os
import logging
from datetime import datetime
from flask import Flask, request, jsonify
import anthropic
import requests

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__)

ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
PORT               = int(os.environ.get("PORT", 8080))

SIGNAL_EMOJI = {
    "TMN+":        "⚡🟢",
    "TMN-":        "⚡🔴",
    "BUY":         "✅🟢",
    "SELL":        "✅🔴",
    "TMN+ Watch":  "👀🟢",
    "TMN- Watch":  "👀🔴",
}

def analyse_signal(payload):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
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

    prompt = f"""You are an expert trading analyst for {sym_mode} ({symbol}) on a {timeframe} chart.

Signal fired: {signal} ({direction}) at price {price}
ATR: {atr} | RSI: {rsi}
Bias: {bias} | Bias Score: {bias_score} | HTF: {htf}
A5 Distance: {a5_dist}x ATR | STMN: {"YES" if stmn else "NO"}
TMA Lower: {tma_lower} | Middle: {tma_middle} | Upper: {tma_upper}
Buy Thresh: {buy_thresh} | Sell Thresh: {sell_thresh}
Zone: {zone}
{f"TL Score: {tl_score}" if tl_score is not None else ""}

Respond in this exact format:

📊 SIGNAL ANALYSIS
Signal quality: [STRONG / MODERATE / WEAK] — [reason]

📈 MARKET CONTEXT
[2-3 sentences on bias, trend, extension]

🎯 TRADE SETUP
Direction: [BUY / SELL / WAIT]
Entry zone: [price]
Stop Loss: [price] ([pts away])
Take Profit 1: [price] ([pts away])
Take Profit 2: [price] ([pts away])
R:R Ratio: [X:1]

⚠️ KEY RISKS
• [risk 1]
• [risk 2]

🔢 CONFIDENCE SCORE: [0-100]%
[one sentence reason]"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text
    except Exception as e:
        log.error(f"Claude error: {e}")
        return f"⚠️ AI analysis unavailable: {e}"

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram not configured")
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
        return r.status_code == 200
    except Exception as e:
        log.error(f"Telegram error: {e}")
        return False

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        payload = request.get_json(force=True)
        if not payload:
            return jsonify({"error": "empty"}), 400

        signal = payload.get("signal", "")
        allowed = ["TMN+", "TMN-", "BUY", "SELL", "TMN+ Watch", "TMN- Watch"]
        if signal not in allowed:
            return jsonify({"status": "ignored"}), 200

        log.info(f"Signal: {signal} {payload.get('symbol')} @ {payload.get('price')}")

        analysis = analyse_signal(payload)
        emoji = SIGNAL_EMOJI.get(signal, "🔔")
        ts = datetime.utcnow().strftime("%H:%M UTC")
        message = (
            f"{emoji} <b>AI Chance v1.2 — {signal}</b>\n"
            f"<b>{payload.get('symbol')}</b> · {payload.get('timeframe')} · {payload.get('price')} · {ts}\n"
            f"{'─'*30}\n\n{analysis}"
        )
        send_telegram(message)
        return jsonify({"status": "ok"}), 200

    except Exception as e:
        log.error(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "version": "1.2"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
