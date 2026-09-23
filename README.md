# AI-Voice-Agent

An intelligent, real-time voice-enabled sales assistant prototype built. Designed to pitch luxury real-estate projects, handle prospect inquiries, manage objections, and automatically sync live CRM lead data using a hybrid local audio and WebSocket-driven FastAPI architecture.

---

## 🛠️ Architecture & Tech Stack
* **Backend & Real-Time Sync:** **FastAPI** and **WebSockets** (`app.py`) acting as the central server to stream live status updates, audio/text transcripts, and CRM state to the UI.
* **Core Voice Pipeline (Python):** 
  * **Speech-to-Text (STT):** `Faster-Whisper` (`base.en`, CPU-optimized `int8`) for instantaneous, low-latency transcription.
  * **Intelligence (LLM):** `Ollama` running `Qwen2.5 / Llama3.2` with custom sales prompt constraints (max 20 words).
  * **Text-to-Speech (TTS):** `Edge-TTS` (`en-US-JennyNeural`) generating natural speech streams.
  * **Audio I/O & Barge-In:** `sounddevice` and `numpy` handling local microphone input, speaker output, and RMS-based interrupt detection.
* **Frontend UI (`static/index.html`):** A modern, responsive real-time dashboard displaying live audio visualizers, chat streams, and a dynamic CRM lead scorecard.
* **CRM Persistence:** Automated slot extraction saving captured prospect metrics into **`captured_leads.json`**.

---

## 📂 Project Structure
```text
emerald-heights-voice-agent/
├── ARCHITECTURE.md          # High-level system architecture and component breakdown
├── TELEPHONY.md             # Production telephony integration strategy (Twilio Media Streams)
├── README.md                # Project documentation and setup guide
├── requirements.txt         # Python dependencies
├── app.py                   # FastAPI backend server & local audio worker
├── static/
│   └── index.html           # Real-time WebSocket web UI dashboard
└── captured_leads.json      # Persistent local CRM storage for extracted prospect leads
```

## 🚀 Setup & Installation Instructions

### Prerequisites
* Python 3.10 or higher installed on your system.
* Ollama installed locally with the required model running:
  ```bash
  cd ollama run qwen2.5:3b
  ```
* **Step 1: Install Dependencies**
  Install all required Python packages via terminal:
  ```bash
  cd pip install -r requirements.txt
  ```
* **Step 2: Run the Application**
  Execute the FastAPI backend script (it will automatically start the Uvicorn server and open the web UI in your browser):
   ```bash
  cd python app.py
  ```
  * **1. Introduction:** Clicking "Start Call" triggers Aria to introduce the Emerald Heights luxury real estate project via local audio and WebSocket broadcast.
  * **2. Dynamic Interaction:** Speak into your local microphone to inquire about pricing, 2/3 BHK unit configurations, and amenities.
  * **3. Real-Time UI Sync:** FastAPI WebSockets instantly update the chat feed and the live CRM priority score/lead fields on index.html.
  * **4. Lead Capture:** Automatically parses prospect details (Name, Phone Number, Budget, Site Visit status) and writes them into captured_leads.json.

## 📞 Production Telephony Strategy
While this working prototype uses a local hardware audio interface (sounddevice) and a WebSocket-powered web dashboard as requested, the full production architecture detailing how to scale this into live carrier phone calls using Twilio Media Streams is fully documented in TELEPHONY.md. 
  
### 🎥 Project Demo Video
👉 [Watch AI Voice Agent Demo]( https://drive.google.com/file/d/1cLOoi1rGNYr-noYbsRR1Vbtb2d4G4tZH/view?usp=sharing )

THANK YOU
Vaishnavi Verma
