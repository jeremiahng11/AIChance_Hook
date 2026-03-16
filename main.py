"""
AI Chance v1.2 — Webhook Server
Receives TradingView alerts → Claude AI analysis → Telegram + M5Stack
"""

import os
import re
import json
import logging
from datetime import datetime, timezone
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
    "TMN+":       "⚡🟢",
    "TMN-":       "⚡🔴",
    "BUY":        "✅🟢",
    "SELL":       "✅🔴",
    "TMN+ Watch": "👀🟢",
    "TMN- Watch": "👀🔴",
}

# ── LATEST SIGNAL STORE (for M5Stack polling) ─────────────
latest_signal = {}

# ── CLAUDE ANALYSIS ───────────────────────────────────────
def analyse_signal(payload: dict) -> dict:
    """Returns structured analysis dict for both Telegram and M5Stack."""
    client    = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    signal    = payload.get("signal", "UNKNOWN")
    symbol    = payload.get("symbol", "UNKNOWN")
    price     = payload.get("price", 0)
    bias_score= payload.get("bias_score", 0)
    htf       = payload.get("htf", "")
    a5_dist   = payload.get("a5_dist", 0)
    stmn      = payload.get("stmn", 0)
    atr       = payload.get("atr", 0)
    tma_lower = payload.get("tma_lower", 0)
    tma_upper = payload.get("tma_upper", 0)
    tma_middle= payload.get("tma_middle", 0)
    buy_thresh= payload.get("buy_thresh", 0)
    sell_thresh=payload.get("sell_thresh", 0)
    rsi       = payload.get("rsi", 0)
    tl_score  = payload.get("tl_score", None)
    timeframe = payload.get("timeframe", "5")
    sym_mode  = payload.get("sym_mode", "Metals")

    direction = "BULLISH" if "+" in signal or signal == "BUY" else "BEARISH"
    zone = ("ABOVE SELL THRESHOLD" if price >= sell_thresh
            else "BELOW BUY THRESHOLD" if price <= buy_thresh
            else "NEUTRAL ZONE")

    prompt = f"""You are an expert trading analyst for {sym_mode} ({symbol}) on a {timeframe}m chart.

Signal: {signal} ({direction}) at {price}
ATR: {atr} | RSI: {rsi} | Bias Score: {bias_score}
HTF: {htf} | A5 Distance: {a5_dist}x | STMN: {"YES" if stmn else "NO"}
TMA Lower: {tma_lower} | Middle: {tma_middle} | Upper: {tma_upper}
Buy Thresh: {buy_thresh} | Sell Thresh: {sell_thresh} | Zone: {zone}
{f"TL Score: {tl_score}" if tl_score else ""}

Respond in EXACTLY this format (no extra text):

QUALITY: [STRONG or MODERATE or WEAK]
DIRECTION: [BUY or SELL or WAIT]
ENTRY: [price or range e.g. 5078-5082]
SL: [price]
TP1: [price]
TP2: [price]
RR: [e.g. 2.3]
CONFIDENCE: [0-100]
CONTEXT: [2-3 sentences on market context, risks, key levels]"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text

        # Parse structured response
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
        return {
            "quality": "WEAK", "direction": "WAIT",
            "entry": str(price), "sl": "", "tp1": "", "tp2": "",
            "rr": "0", "confidence": 0,
            "context": f"AI analysis unavailable: {e}", "raw": ""
        }

# ── TELEGRAM ──────────────────────────────────────────────
def send_telegram(payload: dict, analysis: dict):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    signal = payload.get("signal", "")
    emoji  = SIGNAL_EMOJI.get(signal, "🔔")
    ts     = datetime.now(timezone.utc).strftime("%H:%M UTC")

    q_icon = "🟢" if analysis["quality"] == "STRONG" else "🟡" if analysis["quality"] == "MODERATE" else "🔴"
    c_icon = "🟢" if analysis["confidence"] >= 70 else "🟡" if analysis["confidence"] >= 50 else "🔴"

    msg = (
        f"{emoji} <b>{signal} — {payload.get('symbol')} {payload.get('timeframe')}m</b>\n"
        f"Price: <b>{payload.get('price')}</b> · {ts}\n"
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
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        log.error(f"Telegram error: {e}")

# ── WEBHOOK ───────────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    global latest_signal
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
        send_telegram(payload, analysis)

        # Store for M5Stack polling
        latest_signal = {
            **payload,
            **analysis,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        }

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        log.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

# ── M5STACK POLLING ENDPOINT ──────────────────────────────
@app.route("/latest", methods=["GET"])
def latest():
    """M5Stack polls this endpoint to get the latest signal."""
    return jsonify(latest_signal), 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "version": "1.2"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
