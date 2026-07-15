import streamlit as st
import requests
import json
import re
import time
import matplotlib.pyplot as plt
from collections import Counter, defaultdict
from bs4 import BeautifulSoup

# ---------- KONFIGURATION ----------
URL = "https://www.casino.org/casinoscores/crazy-time/"
MAX_HISTORY = 3000
REFRESH_SECONDS = 10

# ---------- DATEN BESCHAFFEN (robust) ----------
def try_api_fetch():
    """Versucht verschiedene API-Endpunkte, die auf casino.org/casinoscores zu finden sind."""
    endpoints = [
        f"{URL}api/history?limit=5000",
        f"{URL}api/games/crazy-time/spins?limit=5000",
        f"{URL}../api/crazy-time/history?limit=5000",
        "https://www.casino.org/casinoscores/api/crazy-time/history?limit=5000",
        f"{URL}data.json",
        f"{URL}history.json",
        "https://www.casino.org/casinoscores/api/v1/crazy-time/spins?limit=5000",
    ]
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    for ep in endpoints:
        try:
            resp = requests.get(ep, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    for key in ["data", "spins", "history", "results"]:
                        if key in data and isinstance(data[key], list):
                            return data[key]
        except:
            continue
    return []

def parse_html_spins(html):
    """Extrahiert Spins aus HTML – sucht in Tabellen, Divs und Script-Tags."""
    soup = BeautifulSoup(html, "html.parser")
    spins = []

    # --- 1. Versuche, in Script-Tags nach JSON zu suchen (häufig bei SPA) ---
    scripts = soup.find_all("script")
    for script in scripts:
        if script.string:
            # Suche nach Mustern wie window.__INITIAL_STATE__ = {...} oder ähnlich
            match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', script.string, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    # Durchsuche das JSON nach einer Liste von Spins
                    for key in ["spins", "history", "results"]:
                        if key in data and isinstance(data[key], list):
                            return data[key]
                except:
                    pass
            # Suche nach anderen JSON-Objekten, die Spins enthalten
            match = re.search(r'({"spins":\s*\[.*?\]})', script.string, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    if "spins" in data and isinstance(data["spins"], list):
                        return data["spins"]
                except:
                    pass

    # --- 2. Suche in HTML-Tabellen ---
    tables = soup.find_all("table")
    # Fallback: Divs mit Tabelle-ähnlichen Klassen
    if not tables:
        tables = soup.find_all("div", class_=re.compile(r"table|history|spin|result"))

    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 4:
                texts = [col.get_text(strip=True) for col in cols]
                # Prüfe, ob die erste Zelle eine Zeit enthält
                if re.match(r"\d{1,2}:\d{2}", texts[0]):
                    time_str = texts[0]
                    top_slot = texts[1] if len(texts) > 1 else ""
                    wheel = texts[2] if len(texts) > 2 else ""
                    multiplier = texts[3] if len(texts) > 3 else ""
                    # Bereinigung: Wenn "Miss" vorkommt
                    if "Miss" in top_slot:
                        top_slot = "Miss"
                    # Bonuswörter erkennen
                    bonus_keywords = ["Pachinko", "Cash Hunt", "Coin Flip", "Crazy Time"]
                    if any(kw in wheel for kw in bonus_keywords):
                        # wheel bleibt der Bonusname
                        pass
                    spins.append({
                        "time": time_str,
                        "top_slot": top_slot,
                        "wheel": wheel,
                        "multiplier": multiplier
                    })
            # Falls die Zeile nur eine Spalte hat, aber dennoch Informationen enthält (z.B. Bonus)
            elif len(cols) == 1:
                text = cols[0].get_text(strip=True)
                # Suche nach Bonusnamen und Zeit
                bonus_keywords = ["Pachinko", "Cash Hunt", "Coin Flip", "Crazy Time"]
                if any(kw in text for kw in bonus_keywords):
                    # Versuche, eine Zeit zu extrahieren
                    time_match = re.search(r"(\d{1,2}:\d{2})", text)
                    if time_match:
                        time_str = time_match.group(1)
                        # Extrahiere den Bonusnamen
                        bonus_name = next((kw for kw in bonus_keywords if kw in text), "Bonus")
                        spins.append({
                            "time": time_str,
                            "top_slot": "Miss",
                            "wheel": bonus_name,
                            "multiplier": bonus_name
                        })

    # --- 3. Fallback: Durchsuche alle Divs nach Zeilen mit Zeitangaben ---
    if not spins:
        divs = soup.find_all("div")
        for div in divs:
            text = div.get_text(strip=True)
            time_match = re.search(r"(\d{1,2}:\d{2})", text)
            if time_match:
                # Suche nach Zahlen mit X (Multiplikatoren)
                segments = re.findall(r"(\d{1,3}X)", text)
                bonus_keywords = ["Pachinko", "Cash Hunt", "Coin Flip", "Crazy Time"]
                found_bonus = [kw for kw in bonus_keywords if kw in text]
                if segments:
                    top_slot = segments[0] if len(segments) > 0 else "Miss"
                    wheel = segments[1] if len(segments) > 1 else segments[0]
                    spins.append({
                        "time": time_match.group(1),
                        "top_slot": top_slot,
                        "wheel": wheel,
                        "multiplier": f"{top_slot}+{wheel}" if len(segments) > 1 else wheel
                    })
                elif found_bonus:
                    spins.append({
                        "time": time_match.group(1),
                        "top_slot": "Miss",
                        "wheel": found_bonus[0],
                        "multiplier": found_bonus[0]
                    })

    return spins

def fetch_spins():
    """Holt Spins von API oder HTML – gibt eine Liste zurück."""
    # Zuerst API versuchen
    api_data = try_api_fetch()
    if api_data:
        # Konvertiere API-Daten in einheitliches Format
        standardized = []
        for item in api_data:
            if isinstance(item, dict):
                standardized.append({
                    "time": item.get("time") or item.get("timestamp") or "",
                    "top_slot": item.get("top_slot") or item.get("top") or "Miss",
                    "wheel": item.get("wheel") or item.get("segment") or "",
                    "multiplier": item.get("multiplier") or item.get("payout") or ""
                })
        if standardized:
            return standardized

    # Fallback: HTML laden und parsen
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(URL, headers=headers, timeout=10)
        if resp.status_code == 200:
            return parse_html_spins(resp.text)
    except:
        pass
    return []

# ---------- PREDICTION ENGINE (unverändert) ----------
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
st.markdown(f'<meta http-equiv="refresh" content="{REFRESH_SECONDS}">', unsafe_allow_html=True)

# Sound-Script (unverändert)
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

st.title("🎡 Crazy Time Live Prediction")
st.markdown("Aktualisiert automatisch alle **10 Sekunden**. Tippe auf die Seite, um den Sound zu aktivieren.")

# Daten laden
spins = fetch_spins()
if not spins:
    st.error("❌ Keine Spins gefunden. Bitte versuche es später erneut – die Seite hat sich möglicherweise geändert.")
    st.stop()

# Prediction
history = spins[-MAX_HISTORY:] if len(spins) > MAX_HISTORY else spins
prediction = predict_next(history)
if not prediction:
    st.error("Prediction fehlgeschlagen.")
    st.stop()

# ---- Sound-Alarme ----
if "last_spin_time" not in st.session_state:
    st.session_state.last_spin_time = None
if "conf_alert" not in st.session_state:
    st.session_state.conf_alert = False

current_time = prediction["last_spin"].get("time")
if current_time and current_time != st.session_state.last_spin_time:
    if prediction["last_spin"].get("wheel") in {"Pachinko", "Cash Hunt", "Coin Flip", "Crazy Time"}:
        st.markdown('<script>playBonusAlarm();</script>', unsafe_allow_html=True)
    st.session_state.last_spin_time = current_time

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

# ---- Letzte 5 Spins ----
st.subheader("📋 Letzte 5 Spins")
last5 = history[-5:][::-1]
rows = []
for s in last5:
    rows.append({
        "Zeit": s.get("time", ""),
        "Wheel": s.get("wheel", ""),
        "Top-Slot": s.get("top_slot", ""),
        "Multiplikator": s.get("multiplier", "")
    })
st.table(rows)

st.caption("🔊 Sound-Alarm: 2 tiefe Töne = Bonus getroffen  |  1 hoher Ton = Konfidenz > 40%")
