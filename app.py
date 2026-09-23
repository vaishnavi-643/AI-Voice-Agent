import asyncio
import io
import json
import os
import re
import sys
import threading
import time
import webbrowser
from datetime import datetime
import numpy as np
import sounddevice as sd
import soundfile as sf
from faster_whisper import WhisperModel
import edge_tts
import ollama
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
import uvicorn

# ==========================================
# 1. AUDIO & VAD CONFIGURATION
# ==========================================
SAMPLE_RATE = 16000
FRAME_DURATION_MS = 30
FRAME_SIZE = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)

SPEECH_START_THRESHOLD = 700
SILENCE_LEVEL = 500
SILENCE_CHUNKS_LIMIT = 35
MIN_SPEECH_CHUNKS = 14
BARGE_IN_THRESHOLD = 900

agent_state = "IDLE"
interrupt_flag = False
call_active = False
PORT = 8000

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_FILE = os.path.join(BASE_DIR, "static", "index.html")
LEADS_FILE = os.path.join(BASE_DIR, "captured_leads.json")

PROPERTY_FACTS = """
PROJECT: Emerald Heights Luxury Residences
LOCATION: Sector 45, Midtown (Opposite City IT Park, 10 mins from Central Business District).
UNIT CONFIGURATIONS & PRICING:
- 2 BHK: 850 sq.ft carpet area at $450,000 (~3.7 Cr equivalent / secondary inventory from 75 Lakh).
- 3 BHK: 1,250 sq.ft carpet area at $650,000.
POSSESSION: Handover by December 2026. Fully RERA registered and approved.
CONSTRUCTION UPDATE: 14th floor slab completed on schedule.
PAYMENT PLANS:
- 20/80 Construction-linked scheme (Pay 20% now, 80% on possession in 2026).
- Zero-pre-EMI banking tie-ups with leading financial institutions.
AMENITIES: Rooftop infinity pool, clubhouse, automated EV bays, 24/7 security.
RENTAL YIELD: 10-12% expected annual return driven by adjoining IT hub workforce.
SITE VISITS: Daily 10:00 AM to 6:00 PM with complimentary chauffeur pickup.
"""

active_websockets = []
ws_loop = None

def broadcast_ws(event_type: str, data):
    if not active_websockets or not ws_loop:
        return
    msg = json.dumps({"type": event_type, "data": data})
    for ws in list(active_websockets):
        try:
            asyncio.run_coroutine_threadsafe(ws.send_text(msg), ws_loop)
        except Exception:
            pass

# ==========================================
# 2. AGENT CORE ENGINE
# ==========================================
class RealEstateAgent:
    def __init__(self, leads_file=LEADS_FILE):
        print("\n⚡ [INITIALIZING] Loading Faster-Whisper Model...")
        self.stt = WhisperModel("base.en", device="cpu", compute_type="int8")
        self.leads_file = leads_file
        self.lead_memory = {
            "name": None, "phone": None, "unit_type": None, "budget": None,
            "site_visit": {"status": "Pending", "datetime": None},
            "objections_handled": [], "call_status": "Active",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.chat_history = []
        self.save_lead()

    def calculate_lead_score(self) -> str:
        score = 0
        if self.lead_memory.get("name"): score += 15
        if self.lead_memory.get("phone"): score += 25
        if self.lead_memory.get("unit_type"): score += 20
        if self.lead_memory.get("budget"): score += 15
        if self.lead_memory["site_visit"]["status"] == "Confirmed": score += 25
        if score >= 75: return "HOT (High Priority)"
        elif score >= 40: return "WARM (Nurturing)"
        else: return "COLD / INQUIRY"

    def save_lead(self):
        existing = []
        if os.path.exists(self.leads_file):
            try:
                with open(self.leads_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []

        lead_data = {
            "call_id": f"CALL-{id(self)}",
            "timestamp": self.lead_memory["timestamp"],
            "lead_quality": self.calculate_lead_score(),
            "prospect_details": {
                "name": self.lead_memory.get("name") or "Not provided",
                "phone": self.lead_memory.get("phone") or "Not captured",
                "unit_preference": self.lead_memory.get("unit_type") or "Not specified",
                "budget_range": self.lead_memory.get("budget") or "Not captured",
                "site_visit": {
                    "status": self.lead_memory["site_visit"]["status"],
                    "scheduled_time": self.lead_memory["site_visit"]["datetime"] or "Not scheduled"
                }
            },
            "objections_handled": self.lead_memory["objections_handled"],
            "conversation_log": [f"{m['role']}: {m['content']}" for m in self.chat_history if m['role'] != 'system']
        }

        updated = False
        for i, item in enumerate(existing):
            if item.get("timestamp") == self.lead_memory["timestamp"]:
                existing[i] = lead_data
                updated = True
                break
        if not updated:
            existing.append(lead_data)

        with open(self.leads_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=4)

    def extract_slots(self, text: str):
        lower = text.lower()
        name_match = re.search(r"(?:my name is|name is|this is|call me)\s+([a-zA-Z]+(?:\s+[a-zA-Z]+)?)", text, re.IGNORECASE)
        if not name_match:
            fallback_match = re.search(r"\bi am\s+([a-zA-Z]+(?:\s+[a-zA-Z]+)?)\b", text, re.IGNORECASE)
            if fallback_match:
                word = fallback_match.group(1).lower()
                ignore_list = ["there", "here", "looking", "interested", "planning", "going", "fine", "good", "okay", "ready", "just"]
                if not any(ig in word for ig in ignore_list):
                    name_match = fallback_match

        if name_match:
            cand = name_match.group(1).title()
            if cand.lower() not in ["there", "here", "fine", "okay", "ready"]:
                self.lead_memory["name"] = cand

        digits_only = re.sub(r"\D", "", text)
        if len(digits_only) >= 5:
            self.lead_memory["phone"] = digits_only

        if any(w in lower for w in ["2 bhk", "2bhk", "two bedroom", "2 vhg", "2vhg", "2 phk"]):
            self.lead_memory["unit_type"] = "2 BHK"
        elif any(w in lower for w in ["3 bhk", "3bhk", "three bedroom", "3 vhg", "3vhg", "3 phk"]):
            self.lead_memory["unit_type"] = "3 BHK"

        budget_match = re.search(r"(?:budget\s*(?:is|around|of)?\s*)?(\$?\d+[\d,]*\s*(?:k|thousand|lakh|crore|lac|m|million|dollars?))", text, re.IGNORECASE)
        if budget_match:
            self.lead_memory["budget"] = budget_match.group(1).strip()

        if any(w in lower for w in ["visit", "schedule", "tomorrow", "sunday", "saturday", "today", "book", "like to visit", "confirm"]):
            self.lead_memory["site_visit"]["status"] = "Confirmed"
            time_match = re.search(r"\b(today|tomorrow|sunday|saturday|monday|tuesday|wednesday|thursday|friday|\d{1,2}\s*(?:am|pm|\:\d{2}))\b", lower)
            if time_match and not self.lead_memory["site_visit"]["datetime"]:
                self.lead_memory["site_visit"]["datetime"] = text.strip()

        if any(w in lower for w in ["expensive", "costly", "high price", "budget issue", "out of budget"]):
            if "High Price" not in self.lead_memory["objections_handled"]:
                self.lead_memory["objections_handled"].append("High Price")
        if any(w in lower for w in ["late", "delay", "2026", "possession time"]):
            if "Possession Timeline" not in self.lead_memory["objections_handled"]:
                self.lead_memory["objections_handled"].append("Possession Timeline")
        if any(w in lower for w in ["location", "distance", "far away"]):
            if "Location Concerns" not in self.lead_memory["objections_handled"]:
                self.lead_memory["objections_handled"].append("Location Concerns")

        self.save_lead()

    def reply(self, user_text: str) -> str:
        self.extract_slots(user_text)
        collected, needed = [], []
        if self.lead_memory["name"]: collected.append(f"Name: {self.lead_memory['name']}")
        else: needed.append("their name")
        if self.lead_memory["phone"]: collected.append(f"Phone: {self.lead_memory['phone']}")
        else: needed.append("a phone number for confirmation")
        if self.lead_memory["unit_type"]: collected.append(f"Unit: {self.lead_memory['unit_type']}")
        else: needed.append("unit preference (2 or 3 BHK)")
        if self.lead_memory["budget"]: collected.append(f"Budget: {self.lead_memory['budget']}")
        else: needed.append("approximate budget")
        if self.lead_memory["site_visit"]["status"] == "Confirmed":
            if self.lead_memory["site_visit"]["datetime"]:
                collected.append(f"Visit Scheduled: {self.lead_memory['site_visit']['datetime']}")
            else:
                needed.append("a preferred date and time for the visit")
        else:
            needed.append("scheduling a site visit")
            

        next_goal = needed[0] if needed else "wrapping up warmly"

        prompt = f"""You are Aria, real estate sales advisor for Emerald Heights.
KNOWLEDGE BASE:
{PROPERTY_FACTS}
CURRENT LEAD MEMORY:
- CAPTURED: {', '.join(collected) if collected else 'None'}
- PRIMARY NEXT GOAL: Ask for {next_goal}.
RULES:
1. Max 20 words per response. Crystal clear, conversational, friendly.
2. If prospect has an objection, resolve it in sentence 1, then ask for: {next_goal}.
3. No bullet points, headers, or markdown formatting.
4. Do not mention email confirmation. Only phone call and text are valid.
"""
        messages = [{"role": "system", "content": prompt}]
        messages.extend(self.chat_history[-6:])
        messages.append({"role": "user", "content": user_text})

        try:
            res = ollama.chat(model="qwen2.5:3b", messages=messages, options={"temperature": 0.2, "num_predict": 35})
        except Exception:
            res = ollama.chat(model="llama3.2:3b", messages=messages, options={"temperature": 0.2, "num_predict": 35})

        out = res["message"]["content"].replace('"', '').replace('*', '').strip()
        self.chat_history.append({"role": "user", "content": user_text})
        self.chat_history.append({"role": "assistant", "content": out})
        self.save_lead()
        return out

    def transcribe(self, pcm_1d: np.ndarray) -> str:
        float_data = (pcm_1d.astype(np.float32) / 32768.0).flatten()
        segments, _ = self.stt.transcribe(
            float_data, beam_size=1, language="en",
            initial_prompt="Real estate call: 2 BHK, 3 BHK, lakh, crore, site visit, phone number, Subhangi."
        )
        return " ".join([s.text for s in segments]).strip()

agent = RealEstateAgent()

def sync_crm_to_ui():
    broadcast_ws("crm", {
        "score": agent.calculate_lead_score(),
        "name": agent.lead_memory["name"] or "Listening...",
        "phone": agent.lead_memory["phone"] or "Listening...",
        "unit": agent.lead_memory["unit_type"] or "Not specified",
        "budget": agent.lead_memory["budget"] or "Not captured",
        "visit": f"Confirmed ({agent.lead_memory['site_visit']['datetime'] or 'Pending'})" if agent.lead_memory['site_visit']['status'] == "Confirmed" else "Pending",
        "objections": ", ".join(agent.lead_memory["objections_handled"]) if agent.lead_memory["objections_handled"] else "None"
    })

# ==========================================
# 3. LOW-LATENCY TTS & BARGE-IN
# ==========================================
async def play_tts(text: str):
    global agent_state, interrupt_flag
    interrupt_flag = False
    communicate = edge_tts.Communicate(text, "en-US-JennyNeural")
    audio_bytes = bytearray()
    async for chunk in communicate.stream():
        if interrupt_flag: return
        if chunk["type"] == "audio": audio_bytes.extend(chunk["data"])
    if len(audio_bytes) == 0 or interrupt_flag: return

    try:
        data, fs = sf.read(io.BytesIO(audio_bytes), dtype='float32')
        agent_state = "SPEAKING"
        broadcast_ws("status", {"state": "SPEAKING", "label": "🔴 Aria Speaking...", "color": "#f43f5e"})
        sd.play(data, fs)
        while sd.get_stream() and sd.get_stream().active:
            if interrupt_flag:
                sd.stop()
                break
            await asyncio.sleep(0.02)
    except Exception as e:
        print(f"Audio Playback Error: {e}")

    sd.stop()
    if not interrupt_flag:
        agent_state = "LISTENING"
        broadcast_ws("status", {"state": "LISTENING", "label": "🟢 Listening to You...", "color": "#10b981"})

# ==========================================
# 4. HARDWARE AUDIO THREAD
# ==========================================
def audio_worker():
    global agent_state, interrupt_flag, call_active
    audio_chunks = []
    silence_count = 0
    user_talking = False

    def audio_cb(indata, frames, time_info, status):
        nonlocal silence_count, user_talking, audio_chunks
        global agent_state, interrupt_flag
        if not call_active: return

        chunk_mono = indata[:, 0].copy()
        current_rms = np.sqrt(np.mean(chunk_mono.astype(np.float32) ** 2))

        if agent_state == "SPEAKING" and current_rms > BARGE_IN_THRESHOLD:
            interrupt_flag = True
            sd.stop()
            agent_state = "LISTENING"
            broadcast_ws("status", {"state": "INTERRUPTED", "label": "⚡ Interrupted by User", "color": "#f59e0b"})
            broadcast_ws("notice", "⚡ Barge-in: Aria interrupted instantly")
            user_talking = True
            silence_count = 0
            audio_chunks.append(chunk_mono)
            return

        if current_rms > SPEECH_START_THRESHOLD:
            user_talking = True
            silence_count = 0
            audio_chunks.append(chunk_mono)
            if agent_state != "SPEAKING":
                broadcast_ws("status", {"state": "LISTENING", "label": "🟢 User Speaking...", "color": "#10b981"})
        elif user_talking:
            if current_rms <= SILENCE_LEVEL:
                silence_count += 1
            audio_chunks.append(chunk_mono)

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='int16', blocksize=FRAME_SIZE, callback=audio_cb):
        while True:
            time.sleep(0.03)
            if not call_active:
                time.sleep(0.2)
                continue

            if user_talking and silence_count > SILENCE_CHUNKS_LIMIT:
                if len(audio_chunks) < MIN_SPEECH_CHUNKS:
                    audio_chunks = []; user_talking = False; silence_count = 0
                    continue

                raw_pcm = np.concatenate(audio_chunks)
                audio_chunks = []; user_talking = False; silence_count = 0

                agent_state = "PROCESSING"
                broadcast_ws("status", {"state": "PROCESSING", "label": "🟡 Processing Speech...", "color": "#eab308"})
                user_text = agent.transcribe(raw_pcm)

                if len(user_text.strip()) < 3:
                    agent_state = "LISTENING"
                    broadcast_ws("status", {"state": "LISTENING", "label": "🟢 Listening to You...", "color": "#10b981"})
                    continue

                broadcast_ws("message", {"speaker": "You", "text": user_text})
                reply_text = agent.reply(user_text)
                broadcast_ws("message", {"speaker": "Aria", "text": reply_text})
                sync_crm_to_ui()

                asyncio.run(play_tts(reply_text))

# ==========================================
# 5. FASTAPI & WEBSOCKET ROUTES
# ==========================================
app = FastAPI()

@app.get("/")
async def get_index():
    return FileResponse(STATIC_FILE)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global call_active, ws_loop
    await websocket.accept()
    active_websockets.append(websocket)
    ws_loop = asyncio.get_event_loop()

    sync_crm_to_ui()

    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            action = payload.get("action")

            if action == "start":
                call_active = True
                broadcast_ws("status", {"state": "SPEAKING", "label": "🔴 Aria Speaking...", "color": "#f43f5e"})
                broadcast_ws("notice", "🔒 Connected • Hardware Microphone Active")
                intro = "Hello! Thanks for checking out Emerald Heights. How can I help you today?"
                agent.chat_history.append({"role": "assistant", "content": intro})
                broadcast_ws("message", {"speaker": "Aria", "text": intro})
                sync_crm_to_ui()
                threading.Thread(target=lambda: asyncio.run(play_tts(intro)), daemon=True).start()

            elif action == "stop":
                call_active = False
                sd.stop()
                agent.save_lead()
                broadcast_ws("status", {"state": "IDLE", "label": "⚪ Call Terminated", "color": "#64748b"})
                broadcast_ws("notice", "⏹ Call Ended • Safe Shutdown")
                print("\n[PROGRAM EXIT] Call Ended by User. Leads saved to captured_leads.json.")
                threading.Timer(0.8, lambda: os._exit(0)).start()

    except WebSocketDisconnect:
        if websocket in active_websockets:
            active_websockets.remove(websocket)

def open_browser():
    time.sleep(1.2)
    webbrowser.open(f"http://127.0.0.1:{PORT}")

if __name__ == "__main__":
    threading.Thread(target=open_browser, daemon=True).start()
    threading.Thread(target=audio_worker, daemon=True).start()
    print(f"\n🚀 [FASTAPI WEBSOCKET VOICE DESK] Running on http://127.0.0.1:{PORT}")
    uvicorn.run(app, host="127.0.0.1", port=PORT, access_log=False)