"""
AI Chance v1.3 — Webhook Server
TradingView → Claude AI → Telegram + M5Stack
"""

import os, re, json, logging
from datetime import datetime, timezone, timedelta
from flask import Flask, request, jsonify
import anthropic, requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)
SGT = timezone(timedelta(hours=8))

ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
PORT               = int(os.environ.get("PORT", 8080))

SIGNAL_EMOJI = {
    "TMN+":"⚡🟢","TMN-":"⚡🔴","BUY":"✅🟢","SELL":"✅🔴",
    "TMN+ Watch":"👀🟢","TMN- Watch":"👀🔴",
    "BIAS CHANGE":"🔄","PROJ CHANGE":"📊","DO NOTHING":"⏸",
    "STMN+":"🎯🟢","STMN-":"🎯🔴",
}

latest_signal = {}

# ── CLAUDE ANALYSIS ───────────────────────────────────────
def analyse_signal(payload):
    client      = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    signal      = payload.get("signal","")
    symbol      = payload.get("symbol","")
    price       = payload.get("price", 0)
    bias_score  = payload.get("bias_score", 0)
    htf         = payload.get("htf","")
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
    timeframe   = payload.get("timeframe","5")
    sym_mode    = payload.get("sym_mode","Metals")
    projection  = payload.get("projection","UNCERTAIN")

    direction = "BULLISH" if "+" in signal or signal == "BUY" else "BEARISH"
    zone = ("ABOVE SELL THRESHOLD" if price >= sell_thresh
            else "BELOW BUY THRESHOLD" if price <= buy_thresh
            else "NEUTRAL ZONE")

    if signal == "DO NOTHING":
        prompt = f"""You are an expert trading analyst for {sym_mode} ({symbol}) on a {timeframe}m chart.
No trade should be taken right now.
Price: {price} | ATR: {atr} | RSI: {rsi} | Bias: {bias_score} | HTF: {htf}
A5 Dist: {a5_dist}x | Projection: {projection} | Zone: {zone}

Respond in EXACTLY this format:
REASON: [1 sentence why no trade]
WATCH: [1 sentence what to watch for]
CONFIDENCE: [0-100]"""
        try:
            r = client.messages.create(model="claude-sonnet-4-20250514", max_tokens=150,
                messages=[{"role":"user","content":prompt}])
            text = r.content[0].text
            def ex(k): m=re.search(rf"^{k}:\s*(.+)$",text,re.MULTILINE); return m.group(1).strip() if m else ""
            return {"quality":"","direction":"WAIT","entry":"","sl":"","tp1":"","tp2":"","rr":"",
                    "confidence":float(ex("CONFIDENCE") or 0),"context":ex("REASON"),
                    "dn_watch_ai":ex("WATCH"),"raw":text}
        except Exception as e:
            return {"quality":"","direction":"WAIT","entry":"","sl":"","tp1":"","tp2":"","rr":"",
                    "confidence":0,"context":"No clear edge","dn_watch_ai":"","raw":""}

    prompt = f"""You are an expert trading analyst for {sym_mode} ({symbol}) on a {timeframe}m chart.
Signal: {signal} ({direction}) at {price}
ATR: {atr} | RSI: {rsi} | Bias Score: {bias_score} | HTF: {htf}
A5 Distance: {a5_dist}x | STMN: {"YES" if stmn else "NO"} | Projection: {projection}
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
        r = client.messages.create(model="claude-sonnet-4-20250514", max_tokens=400,
            messages=[{"role":"user","content":prompt}])
        text = r.content[0].text
        log.info(f"Claude: {text[:80]}")
        def ex(k): m=re.search(rf"^{k}:\s*(.+)$",text,re.MULTILINE); return m.group(1).strip() if m else ""
        return {"quality":ex("QUALITY"),"direction":ex("DIRECTION"),"entry":ex("ENTRY"),
                "sl":ex("SL"),"tp1":ex("TP1"),"tp2":ex("TP2"),"rr":ex("RR"),
                "confidence":float(ex("CONFIDENCE") or 0),"context":ex("CONTEXT"),"raw":text}
    except Exception as e:
        log.error(f"Claude error: {e}")
        return {"quality":"","direction":"","entry":"","sl":"","tp1":"","tp2":"","rr":"",
                "confidence":0,"context":f"AI error: {e}","raw":""}

# ── TELEGRAM ──────────────────────────────────────────────
def send_telegram(payload, analysis):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    def post_msg(msg):
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id":TELEGRAM_CHAT_ID,"text":msg,"parse_mode":"HTML"},
                timeout=10)
            d = resp.json()
            if d.get("ok"):
                log.info("Telegram sent ✓")
                return True
            log.error(f"Telegram failed: {d}")
            return False
        except Exception as e:
            log.error(f"Telegram error: {e}")
            return False

    signal     = payload.get("signal","")
    projection = payload.get("projection","UNCERTAIN")
    bias_dir   = payload.get("bias_dir","NEUTRAL")
    prev_bias  = payload.get("prev_bias","")
    prev_proj  = payload.get("prev_proj","")
    ts         = datetime.now(SGT).strftime("%H:%M SGT")

    if signal == "BIAS CHANGE":
        b_icon = "🟢" if bias_dir=="BIAS UP" else "🔴" if bias_dir=="BIAS DOWN" else "⚪"
        return post_msg(f"🔄 <b>BIAS CHANGED — {payload.get('symbol')} {payload.get('timeframe')}m</b>\n"
                        f"{prev_bias} → <b>{b_icon} {bias_dir}</b>\n"
                        f"Price: {payload.get('price')} · {ts}\n"
                        f"Projection: {projection} | HTF: {payload.get('htf')} | Score: {payload.get('bias_score')}")

    if signal == "PROJ CHANGE":
        p_icon = "📈" if "UP" in projection else "📉" if "DOWN" in projection else "↔"
        return post_msg(f"📊 <b>PROJECTION CHANGED — {payload.get('symbol')} {payload.get('timeframe')}m</b>\n"
                        f"{prev_proj} → <b>{p_icon} {projection}</b>\n"
                        f"Price: {payload.get('price')} · {ts}\n"
                        f"Bias: {bias_dir} | HTF: {payload.get('htf')} | RSI: {payload.get('rsi')}")

    if signal == "DO NOTHING":
        dn_reason  = analysis.get("context","No clear edge")
        dn_watch   = analysis.get("dn_watch_ai","Watch bias label for direction")
        confidence = int(analysis.get("confidence",0))
        c_icon     = "🟢" if confidence>=70 else "🟡" if confidence>=50 else "🔴"
        return post_msg(f"⏸ <b>DO NOTHING — {payload.get('symbol')} {payload.get('timeframe')}m</b>\n"
                        f"Price: {payload.get('price')} · {ts}\n"
                        f"{'─'*28}\n\n"
                        f"<b>Reason:</b> {dn_reason}\n\n"
                        f"<b>Watch:</b> {dn_watch}\n\n"
                        f"Bias: {bias_dir} | Proj: {projection} | HTF: {payload.get('htf')}\n"
                        f"{c_icon} Confidence: {confidence}%")

    if signal in ("STMN+","STMN-"):
        is_bull = signal == "STMN+"
        s_icon  = "🟢" if is_bull else "🔴"
        zone    = payload.get("zone","")
        return post_msg(f"🎯{s_icon} <b>{signal} — {payload.get('symbol')} {payload.get('timeframe')}m</b>\n"
                        f"Price entered <b>{'BUY' if is_bull else 'SELL'} zone</b> · {ts}\n"
                        f"Price: {payload.get('price')} | Zone: {zone}\n"
                        f"{'─'*28}\n"
                        f"Bias: {bias_dir} | HTF: {payload.get('htf')} | RSI: {payload.get('rsi')}\n"
                        f"Proj: {projection} | A5 dist: {payload.get('a5_dist')}x\n\n"
                        f"⚠️ <b>Watch for {signal} confirmation</b>")

    # Full AI analysis for trading signals
    EMAP = {"TMN+":"⚡🟢","TMN-":"⚡🔴","BUY":"✅🟢","SELL":"✅🔴",
            "TMN+ Watch":"👀🟢","TMN- Watch":"👀🔴"}
    emoji  = EMAP.get(signal,"🔔")
    q_icon = "🟢" if analysis["quality"]=="STRONG" else "🟡" if analysis["quality"]=="MODERATE" else "🔴"
    c_icon = "🟢" if analysis["confidence"]>=70 else "🟡" if analysis["confidence"]>=50 else "🔴"
    return post_msg(
        f"{emoji} <b>{signal} — {payload.get('symbol')} {payload.get('timeframe')}m</b>\n"
        f"Price: <b>{payload.get('price')}</b> · {ts}\n"
        f"Bias: <b>{bias_dir}</b> | Projection: <b>{projection}</b>\n"
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

# ── WEBHOOK ───────────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    global latest_signal
    try:
        payload = request.get_json(force=True)
        if not payload:
            log.error("Empty payload")
            return jsonify({"error":"empty"}), 400

        signal = payload.get("signal","")
        log.info(f"Webhook: {signal} {payload.get('symbol')} @ {payload.get('price')}")
        log.info(f"Payload: {json.dumps(payload)}")

        allowed = ["TMN+","TMN-","BUY","SELL","TMN+ Watch","TMN- Watch",
                   "BIAS CHANGE","PROJ CHANGE","DO NOTHING","STMN+","STMN-"]
        if signal not in allowed:
            log.info(f"Ignored: {signal}")
            return jsonify({"status":"ignored"}), 200

        lightweight = ["BIAS CHANGE","PROJ CHANGE","STMN+","STMN-"]
        analysis = ({"quality":"","direction":"","entry":"","sl":"","tp1":"","tp2":"",
                     "rr":"","confidence":0,"context":"","raw":""}
                    if signal in lightweight else analyse_signal(payload))

        send_telegram(payload, analysis)

        latest_signal = {**payload, **analysis,
                         "dn_reason": analysis.get("context",""),
                         "dn_watch":  analysis.get("dn_watch_ai",""),
                         "timestamp": datetime.now(SGT).strftime("%Y-%m-%dT%H:%M:%S+08:00")}

        return jsonify({"status":"ok"}), 200

    except Exception as e:
        log.error(f"Webhook error: {e}", exc_info=True)
        return jsonify({"error":str(e)}), 500

@app.route("/latest", methods=["GET"])
def latest():
    return jsonify(latest_signal), 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status":"ok","version":"1.3",
        "anthropic_key":"set" if ANTHROPIC_API_KEY else "MISSING",
        "telegram_token":"set" if TELEGRAM_BOT_TOKEN else "MISSING",
        "telegram_chat":"set" if TELEGRAM_CHAT_ID else "MISSING",
    }), 200

if __name__ == "__main__":
    log.info(f"Starting on port {PORT}")
    app.run(host="0.0.0.0", port=PORT)
