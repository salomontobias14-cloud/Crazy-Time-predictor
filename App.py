import streamlit as st
import requests
import json
import re
import time
import matplotlib.pyplot as plt
from collections import Counter, defaultdict

# ---------- KONFIGURATION ----------
URL = "https://www.casino.org/casinoscores/crazy-time/"
MAX_HISTORY = 3000
REFRESH_SECONDS = 10

# ---------- DATEN BESCHAFFEN ----------
def try_api_fetch():
    endpoints = [
        f"{URL}api/history?limit=5000",
        f"{URL}api/games/crazy-time/spins?limit=5000",
        f"{URL}../api/crazy-time/history?limit=5000",
        "https://www.casino.org/casinoscores/api/crazy-time/history?limit=5000",
    ]
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    for ep in endpoints:
        try:
            resp = requests.get(ep, headers=headers, timeout=4)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    for k in ["data", "spins", "history", "results"]:
                        if k in data and isinstance(data[k], list):
                            return data[k]
        except:
            continue
    return []

def parse_html_spins(html):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    spins = []
    rows = soup.find_all("tr")
    if not rows:
        rows = soup.find_all("div", class_="row")
    
    for row in rows:
        text = row.get_text(" ", strip=True)
        if not re.search(r"\d{1,2}:\d{2}", text):
            continue
        
        time_match = re.search(r"(\d{1,2}:\d{2})", text)
        time_str = time_match.group(1)
        segments = re.findall(r"(\d{1,3}X)", text)
        bonus_keywords = ["Pachinko", "Cash Hunt", "Coin Flip", "Crazy Time"]
        found_bonus = [kw for kw in bonus_keywords if kw in text]
        
        if len(segments) >= 2:
            top = segments[0]
            wheel = segments[1]
            spins.append({
                "time": time_str,
                "top_slot": top,
                "wheel": wheel,
                "multiplier": f"{top} + {wheel}"
            })
        elif found_bonus:
            spins.append({
                "time": time_str,
                "top_slot": "Miss",
                "wheel": found_bonus[0],
                "multiplier": found_bonus[0]
            })
    return spins

def fetch_spins():
    api_data = try_api_fetch()
    if api_data:
        return api_data
    
    try:
        resp = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if resp.status_code == 200:
            return parse_html_spins(resp.text)
    except:
        pass
    return []

# ---------- PREDICTION ENGINE ----------
def weighted_frequency(spins, key, decay=0.92):
    counts = defaultdict(float)
    total = 0.0
    for i, s in enumerate(spins):
        weight = decay ** (len(spins) - 1 - i)
        val = s.get(key, "Unknown")
        counts[val] += weight
        total += weight
    return {k: v/total for k, v in counts.items()}

def build_markov(spins, key):
    matrix = defaultdict(Counter)
    for i in range(len(spins)-1):
        cur = spins[i].get(key, "Unknown")
        nxt = spins[i+1].get(key, "Unknown")
        matrix[cur][nxt] += 1
    for state in matrix:
        total = sum(matrix[state].values())
        for nxt in matrix[state]:
            matrix[state][nxt] /= total
    return matrix

def predict_next(spins):
    if not spins:
        return None
    
    wheel_probs = weighted_frequency(spins, "wheel", decay=0.90)
    top_probs = weighted_frequency(spins, "top_slot", decay=0.90)
    
    markov = build_markov(spins, "wheel")
    last_wheel = spins[-1].get("wheel", "Unknown")
    markov_pred = markov.get(last_wheel, {})
    
    bonus_names = {"Pachinko", "Cash Hunt", "Coin Flip", "Crazy Time"}
    last_bonus_idx = -1
    for i in range(len(spins)-1, -1, -1):
        if spins[i].get("wheel") in bonus_names:
            last_bonus_idx = i
            break
    current_gap = len(spins) - 1 - last_bonus_idx if last_bonus_idx != -1 else len(spins)
    avg_interval = 10.5
    bonus_score = min(current_gap / avg_interval, 2.5)
    
    combined = {}
    all_seg = set(wheel_probs.keys()) | set(markov_pred.keys())
    for seg in all_seg:
        prob = wheel_probs.get(seg, 0) * 0.55
        prob += markov_pred.get(seg, 0) * 0.30
        if bonus_score > 1.0 and seg in bonus_names:
            prob += (bonus_score - 1.0) * 0.15
        combined[seg] = prob
    
    sorted_wheel = sorted(combined.items(), key=lambda x: -x[1])
    best_wheel = sorted_wheel[0][0] if sorted_wheel else "1X"
    best_top = max(top_probs, key=top_probs.get) if top_probs else "1X"
    
    confidence = (sorted_wheel[0][1] - sorted_wheel[1][1]) * 100 if len(sorted_wheel) > 1 else 50.0
    
    return {
        "predicted_wheel": best_wheel,
        "predicted_top": best_top,
        "confidence": round(confidence, 1),
        "bonus_score": round(bonus_score, 2),
        "combined_probs": dict(combined),
        "last_spin": spins[-1],
        "total": len(spins)
    }

# ---------- STREAMLIT UI ----------
st.set_page_config(page_title="🎡 Crazy Time Predictor", layout="centered")

# Meta-Refresh für automatische Aktualisierung
st.markdown(f'<meta http-equiv="refresh" content="{REFRESH_SECONDS}">', unsafe_allow_html=True)

# Sound-Funktionen (JavaScript)
st.markdown("""
<script>
function playBonusAlarm() {
    try {
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        for (let i=0; i<2; i++) {
            const osc = audioCtx.createOscillator();
            const gain = audioCtx.createGain();
            osc.connect(gain);
            gain.connect(audioCtx.destination);
            osc.frequency.value = 400;
            gain.gain.value = 0.3;
            osc.start();
            osc.stop(audioCtx.currentTime + 0.15);
            // kleine Pause zwischen den Tönen
            if (i === 0) setTimeout(() => {}, 200);
        }
    } catch(e) {}
}
function playConfidenceAlarm() {
    try {
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        osc.frequency.value = 1500;
        gain.gain.value = 0.3;
        osc.start();
        osc.stop(audioCtx.currentTime + 0.3);
    } catch(e) {}
}
</script>
""", unsafe_allow_html=True)

# Titel und Beschreibung
st.title("🎡 Crazy Time Live Prediction")
st.markdown("Aktualisiert automatisch alle **10 Sekunden**. Tippe auf die Seite, um den Sound zu aktivieren.")

# Daten laden
spins = fetch_spins()
if not spins:
    st.error("❌ Keine Spins gefunden. Die Seite könnte geändert worden sein.")
    st.stop()

history = spins[-MAX_HISTORY:] if len(spins) > MAX_HISTORY else spins
prediction = predict_next(history)

if not prediction:
    st.error("Prediction fehlgeschlagen.")
    st.stop()

# ---- Sound-Alarme auslösen (via JavaScript) ----
# Wir speichern den letzten Spin-Zeitstempel im Session State, um nur bei neuen Spins zu alarmieren
if "last_spin_time" not in st.session_state:
    st.session_state.last_spin_time = None
if "conf_alert" not in st.session_state:
    st.session_state.conf_alert = False

current_time = prediction["last_spin"].get("time")
if current_time and current_time != st.session_state.last_spin_time:
    # Neuer Spin – prüfe auf Bonus
    if prediction["last_spin"].get("wheel") in {"Pachinko", "Cash Hunt", "Coin Flip", "Crazy Time"}:
        st.markdown('<script>playBonusAlarm();</script>', unsafe_allow_html=True)
    st.session_state.last_spin_time = current_time

# Konfidenz-Alarm (einmalig)
conf = prediction["confidence"]
if conf >= 40.0 and not st.session_state.conf_alert:
    st.markdown('<script>playConfidenceAlarm();</script>', unsafe_allow_html=True)
    st.session_state.conf_alert = True
elif conf < 40.0:
    st.session_state.conf_alert = False

# ---- Grafik ----
fig, ax = plt.subplots(figsize=(10, 5))
probs = prediction["combined_probs"]
sorted_items = sorted(probs.items(), key=lambda x: -x[1])[:10]
labels = [x[0] for x in sorted_items]
values = [x[1] * 100 for x in sorted_items]
colors = ['#2ecc71' if lab == prediction["predicted_wheel"] else '#3498db' for lab in labels]
ax.bar(labels, values, color=colors)
ax.set_ylabel("Wahrscheinlichkeit (%)")
ax.set_xlabel("Wheel-Segment")
ax.set_title(f"🔮 Prediction: {prediction['predicted_wheel']}  (Konfidenz: {conf}%)")
for i, v in enumerate(values):
    ax.text(i, v + 0.5, f"{v:.1f}%", ha="center")
ax.grid(axis='y', linestyle='--', alpha=0.3)
st.pyplot(fig)

# ---- Metadaten ----
col1, col2, col3 = st.columns(3)
col1.metric("🎯 Top-Slot", prediction['predicted_top'])
col2.metric("📈 Konfidenz", f"{conf}%")
col3.metric("⏳ Bonus-Overdue", f"{prediction['bonus_score']}x")

st.info(
    f"**Letzter Spin:** {prediction['last_spin'].get('wheel', '-')} @ {prediction['last_spin'].get('time', '-')}  |  "
    f"**Basis:** {prediction['total']} Spins analysiert"
)

# ---- Letzte 5 Spins als Tabelle ----
st.subheader("📋 Letzte 5 Spins")
last5 = history[-5:][::-1]  # neueste zuerst
rows = []
for s in last5:
    rows.append({
        "Zeit": s.get("time", ""),
        "Wheel": s.get("wheel", ""),
        "Top-Slot": s.get("top_slot", ""),
        "Multiplikator": s.get("multiplier", "")
    })
st.table(rows)

# ---- Hinweis zum Sound ----
st.caption("🔊 Sound-Alarm: 2 tiefe Töne = Bonus getroffen  |  1 hoher Ton = Konfidenz > 40%")
