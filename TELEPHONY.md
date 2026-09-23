# Emerald Heights: Production Telephony Integration Strategy

## 1. Overview
While the current working prototype utilizes a local hardware audio interface (`sounddevice` via Python) and a WebSocket-driven web UI dashboard (`index.html`) for local evaluation and demonstration, this document outlines the production-grade strategy required to scale the "Aria" AI voice agent into a live telecommunications carrier network for inbound and outbound customer phone calls.

---

## 2. Recommended Production Telephony Solution: Twilio Media Streams
For production deployment, **Twilio Media Streams** combined with bi-directional **WebSockets** is the ideal architecture.

### Justification:
* **Real-Time Latency:** Twilio Media Streams allows raw audio streaming over standard WebSockets using telecom-standard codecs (PCM 8kHz/16kHz), which matches the strict sub-second latency requirements needed for natural voice conversations.
* **Global Scale & Reliability:** Leverages a robust carrier cloud infrastructure with high uptime and global numbers availability.
* **SIP Trunking Flexibility:** Can seamlessly bridge with enterprise SIP trunks if corporate clients require integration with their existing telephony hardware or contact center infrastructure.

---

## 3. Step-by-Step Telephony Bridge Implementation Strategy

To transition from the local `sounddevice` worker to live telecom phone lines, the backend architecture adapts through the following steps:

### Step 1: Carrier Webhook Configuration
Configure a Twilio phone number webhook to point to a secure public HTTPS/WSS endpoint hosted on a cloud server (e.g., AWS, GCP, or via secure tunnels like Ngrok for staging environments). When a customer calls the number, Twilio initiates a WebSocket stream session.

### Step 2: Inbound Media Stream Handling
Replace the local microphone input loop with Twilio's incoming media stream payload handler:
* **Audio Ingestion:** Twilio streams real-time audio packets (base64-encoded audio chunks) from the active call into the server.
* **Processing Pipeline:** These incoming telephone audio frames are fed directly into the `Faster-Whisper` STT engine instead of the local microphone buffer.

### Step 3: AI Intelligence Pipeline (Unchanged)
The core conversational reasoning layer remains identical to the current implementation:
1. **STT:** Whisper transcribes the phone audio stream into text.
2. **LLM:** Ollama (`Qwen2.5`) processes the transcript against property rules and handles objections.
3. **TTS:** `Edge-TTS` generates the natural response audio stream.

### Step 4: Outbound Audio Streaming to Carrier
Instead of executing local speaker playback via `sd.play()`, the synthesized audio chunks from Edge-TTS are encoded into base64 media payloads and streamed back through the active Twilio WebSocket connection, allowing the caller to hear Aria instantly over their telephone handset.

---

## 4. Production Security & Multi-User Session Management
* **Secure WebSockets (`wss://`):** Ensure valid SSL/TLS certificates are enforced on the production server to secure data transmission.
* **Call SID Tracking:** Map each unique Twilio `CallSid` to independent `RealEstateAgent` state instances. This ensures concurrent multi-user phone calls maintain isolated conversation histories and write separately to the persistence layer.
