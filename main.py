"""
AI Chance v1.2 — Webhook Server
"""

import os
import re
import json
import logging
from datetime import datetime, timezone
from flask import Flask, request, jsonify
import anthropic
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)

ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
PORT               = int(os.environ.get("PORT", 8080))

SIGNAL_EMOJI = {
    "TMN+":       "⚡🟢",
    "TMN-":       "⚡🔴",
    "BUY":        "✅🟢",
    "SELL":       "✅🔴",
    "TMN+ Watch": "👀🟢",
    "TMN- Watch": "👀🔴",
}

latest_signal = {}

def analyse_signal(payload):
    log.info("Calling Claude API...")
    if not ANTHROPIC_API_KEY:
        log.error("ANTHROPIC_API_KEY not set!")
        return {"quality":"WEAK","direction":"WAIT","entry":str(payload.get("price","")),"sl":"","tp1":"","tp2":"","rr":"0","confidence":0,"context":"API key not configured","raw":""}

    client     = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    signal     = payload.get("signal","UNKNOWN")
    symbol     = payload.get("symbol","UNKNOWN")
    price      = payload.get("price", 0)
    bias_score = payload.get("bias_score", 0)
    htf        = payload.get("htf","")
    a5_dist    = payload.get("a5_dist", 0)
    stmn       = payload.get("stmn", 0)
    atr        = payload.get("atr", 0)
    tma_lower  = payload.get("tma_lower", 0)
    tma_upper  = payload.get("tma_upper", 0)
    tma_middle = payload.get("tma_middle", 0)
    buy_thresh = payload.get("buy_thresh", 0)
    sell_thresh= payload.get("sell_thresh", 0)
    rsi        = payload.get("rsi", 0)
    tl_score   = payload.get("tl_score", None)
    timeframe  = payload.get("timeframe","5")
    sym_mode   = payload.get("sym_mode","Metals")
    projection = payload.get("projection","UNCERTAIN")

    direction = "BULLISH" if "+" in signal or signal == "BUY" else "BEARISH"
    zone = ("ABOVE SELL THRESHOLD" if price >= sell_thresh
            else "BELOW BUY THRESHOLD" if price <= buy_thresh
            else "NEUTRAL ZONE")

    prompt = f"""You are an expert trading analyst for {sym_mode} ({symbol}) on a {timeframe}m chart.

Signal: {signal} ({direction}) at {price}
ATR: {atr} | RSI: {rsi} | Bias Score: {bias_score}
HTF: {htf} | A5 Distance: {a5_dist}x | STMN: {"YES" if stmn else "NO"}
Projection: {projection}
TMA Lower: {tma_lower} | Middle: {tma_middle} | Upper: {tma_upper}
Buy Thresh: {buy_thresh} | Sell Thresh: {sell_thresh} | Zone: {zone}
{f"TL Score: {tl_score}" if tl_score else ""}

Respond in EXACTLY this format:

QUALITY: [STRONG or MODERATE or WEAK]
DIRECTION: [BUY or SELL or WAIT]
ENTRY: [price or range]
SL: [price]
TP1: [price]
TP2: [price]
RR: [number]
CONFIDENCE: [0-100]
CONTEXT: [2-3 sentences]"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text
        log.info(f"Claude response received: {text[:100]}")

        def extract(key):
            m = re.search(rf"^{key}:\s*(.+)$", text, re.MULTILINE)
            return m.group(1).strip() if m else ""

        return {
            "quality":    extract("QUALITY"),
            "direction":  extract("DIRECTION"),
            "entry":      extract("ENTRY"),
            "sl":         extract("SL"),
            "tp1":        extract("TP1"),
            "tp2":        extract("TP2"),
            "rr":         extract("RR"),
            "confidence": float(extract("CONFIDENCE") or 0),
            "context":    extract("CONTEXT"),
            "raw":        text
        }
    except Exception as e:
        log.error(f"Claude error: {e}")
        return {"quality":"WEAK","direction":"WAIT","entry":str(price),"sl":"","tp1":"","tp2":"","rr":"0","confidence":0,"context":f"AI error: {e}","raw":""}


def send_telegram(payload, analysis):
    log.info(f"Sending Telegram to chat_id={TELEGRAM_CHAT_ID}")
    if not TELEGRAM_BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN not set!")
        return False
    if not TELEGRAM_CHAT_ID:
        log.error("TELEGRAM_CHAT_ID not set!")
        return False

    signal     = payload.get("signal","")
    projection = payload.get("projection","UNCERTAIN")
    emoji  = SIGNAL_EMOJI.get(signal,"🔔")
    ts     = datetime.now(timezone.utc).strftime("%H:%M UTC")
    q_icon = "🟢" if analysis["quality"] == "STRONG" else "🟡" if analysis["quality"] == "MODERATE" else "🔴"
    c_icon = "🟢" if analysis["confidence"] >= 70 else "🟡" if analysis["confidence"] >= 50 else "🔴"

    msg = (
        f"{emoji} <b>{signal} — {payload.get('symbol')} {payload.get('timeframe')}m</b>\n"
        f"Price: <b>{payload.get('price')}</b> · {ts}\n"
        f"Projection: <b>{projection}</b>\n"
        f"{'─'*28}\n\n"
        f"{q_icon} <b>Quality:</b> {analysis['quality']}\n\n"
        f"📈 <b>Context:</b>\n{analysis['context']}\n\n"
        f"🎯 <b>Trade Setup:</b>\n"
        f"Direction: <b>{analysis['direction']}</b>\n"
        f"Entry: {analysis['entry']}\n"
        f"Stop Loss: {analysis['sl']}\n"
        f"TP1: {analysis['tp1']}  TP2: {analysis['tp2']}\n"
        f"R:R = {analysis['rr']}:1\n\n"
        f"{c_icon} <b>Confidence: {int(analysis['confidence'])}%</b>"
    )

    try:
        url  = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       msg,
            "parse_mode": "HTML"
        }, timeout=10)
        data = resp.json()
        if data.get("ok"):
            log.info("Telegram message sent ✓")
            return True
        else:
            log.error(f"Telegram failed: {data}")
            return False
    except Exception as e:
        log.error(f"Telegram error: {e}")
        return False


@app.route("/webhook", methods=["POST"])
def webhook():
    global latest_signal
    try:
        payload = request.get_json(force=True)
        if not payload:
            log.error("Empty payload received")
            return jsonify({"error": "empty"}), 400

        signal = payload.get("signal","")
        log.info(f"Webhook received: signal={signal} symbol={payload.get('symbol')} price={payload.get('price')}")
        log.info(f"Full payload: {json.dumps(payload)}")

        allowed = ["TMN+","TMN-","BUY","SELL","TMN+ Watch","TMN- Watch"]
        if signal not in allowed:
            log.info(f"Signal '{signal}' not in allowed list — ignored")
            return jsonify({"status":"ignored","signal":signal}), 200

        analysis = analyse_signal(payload)
        sent     = send_telegram(payload, analysis)

        latest_signal = {
            **payload,
            **analysis,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        }

        return jsonify({"status":"sent" if sent else "telegram_failed","signal":signal}), 200

    except Exception as e:
        log.error(f"Webhook error: {e}", exc_info=True)
        return jsonify({"error":str(e)}), 500


@app.route("/latest", methods=["GET"])
def latest():
    return jsonify(latest_signal), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status":        "ok",
        "version":       "1.2",
        "anthropic_key": "set" if ANTHROPIC_API_KEY else "MISSING",
        "telegram_token":"set" if TELEGRAM_BOT_TOKEN else "MISSING",
        "telegram_chat": "set" if TELEGRAM_CHAT_ID else "MISSING"
    }), 200


if __name__ == "__main__":
    log.info(f"Starting on port {PORT}")
    app.run(host="0.0.0.0", port=PORT)
