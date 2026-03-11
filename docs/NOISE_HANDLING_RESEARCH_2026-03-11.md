# Handling Background Noise & Multiple Speakers in Drive-Through Environments

**Date:** 2026-03-11
**Context:** Brew is a real-time voice AI drive-through ordering system using Gemini Live API (speech-to-speech) via Google ADK, with a browser frontend capturing 16 kHz PCM audio and streaming it over WebSocket.

---

## Table of Contents

1. [The Problem](#1-the-problem)
2. [Current Brew Architecture & Gaps](#2-current-brew-architecture--gaps)
3. [Layer 1: Hardware-Level Solutions](#3-layer-1-hardware-level-solutions)
4. [Layer 2: Client-Side Audio Preprocessing (Browser)](#4-layer-2-client-side-audio-preprocessing-browser)
5. [Layer 3: Gemini Live API Configuration](#5-layer-3-gemini-live-api-configuration)
6. [Layer 4: Server-Side Audio Processing](#6-layer-4-server-side-audio-processing)
7. [Layer 5: Prompt Engineering & Agent Behavior](#7-layer-5-prompt-engineering--agent-behavior)
8. [Layer 6: Speaker Diarization (Multi-Speaker)](#8-layer-6-speaker-diarization-multi-speaker)
9. [What Industry Leaders Do](#9-what-industry-leaders-do)
10. [Recommended Implementation Roadmap](#10-recommended-implementation-roadmap)
11. [Cost & Complexity Comparison](#11-cost--complexity-comparison)
12. [References](#12-references)

---

## 1. The Problem

Drive-through environments are among the harshest audio environments for speech recognition:

| Noise Source | Characteristics | Impact |
|---|---|---|
| **Engine idling/revving** | Low-frequency rumble, 60-90 dB | Masks speech fundamentals |
| **Wind** | Broadband, unpredictable | Causes pops, distortion |
| **Other cars** | Horns, music from other vehicles | Sudden transient noise |
| **Multiple passengers** | Overlapping speech, side conversations | Confuses turn detection and intent |
| **Kitchen/equipment** | Fans, fryers, blenders | Steady-state background |
| **Rain/weather** | Broadband noise on microphone | Degrades SNR significantly |
| **Intercom feedback** | Echo, speaker bleed | Can trigger self-listening loops |

The core challenges for Brew:
- **False triggers**: Background noise causes the AI to think someone is speaking, leading to nonsensical responses or unwanted language switches.
- **Missed speech**: Legitimate customer speech is drowned out by noise.
- **Multi-speaker confusion**: Passengers talking among themselves get interpreted as order commands.
- **Barge-in misfires**: Noise triggers barge-in, cutting off the AI mid-response.

---

## 2. Current Brew Architecture & Gaps

### What Brew Does Today

```
[Microphone @ 48kHz] → [hark VAD (threshold: -35dB)] → [Resample to 16kHz PCM]
    → [WebSocket] → [Gemini Live API via ADK run_live()]
```

**Frontend (`audioPipeline.ts`):**
- Captures audio via `getUserMedia({ audio: true })` — uses browser defaults for echo cancellation, noise suppression, auto gain control.
- Uses `hark` library for client-side VAD with `threshold: -35` and `interval: 100ms`.
- Resamples from 48kHz to 16kHz 16-bit PCM via AudioWorklet (or ScriptProcessor fallback).
- Sends raw PCM chunks over WebSocket.

**Backend (`main.py`):**
- Streams raw PCM directly to Gemini Live API via `runner.run_live()`.
- No audio preprocessing on the server side.
- Uses default `RunConfig` with no `realtime_input_config` (relies on Gemini's default VAD).

**System Prompt (`system_prompt_09.md`):**
- Has an "ANTI-HALLUCINATION RULE" for background noise causing language switches.
- Has an "INTERRUPTIONS & BACKGROUND NOISE" section telling the agent to stay silent on noise-only interrupts.

### Identified Gaps

| Gap | Impact |
|---|---|
| No dedicated noise suppression layer | Raw environmental noise hits Gemini directly |
| hark threshold at -35dB is relatively sensitive | Noise above -35dB triggers "speaking" state |
| Browser's built-in noise suppression is on by default but generic | Not optimized for outdoor/drive-through environments |
| No server-side audio preprocessing | Missed opportunity to clean audio before API |
| Gemini VAD uses defaults | No tuning for noisy environments |
| No speaker diarization | Cannot distinguish customer from passengers |

---

## 3. Layer 1: Hardware-Level Solutions

Hardware is the first and most impactful line of defense. Even the best software cannot fully recover a signal that was poorly captured.

### 3.1 Directional / Cardioid Microphones

Standard drive-through microphones (omnidirectional) pick up sound from all directions. Switching to a **unidirectional (cardioid) or supercardioid microphone** pointed at the driver's window dramatically reduces pickup of engine noise, other cars, and passenger conversations.

**Industry standard:** Panasonic Attune II system uses a uni-directional electret condenser microphone with 110 dBSPL max input, combined with 4 levels of digital noise reduction.

**Recommendation:** If Brew is deployed on physical hardware, use a directional microphone aimed at the order point. This alone can improve SNR by 10-15 dB.

### 3.2 Microphone Arrays & Beamforming

Multiple microphones arranged in an array can use **beamforming** to create a virtual directional beam focused on the speaker:

- **Delay-and-sum beamforming**: Simplest approach, aligns signals by time delay.
- **MVDR (Minimum Variance Distortionless Response)**: Adaptive, suppresses noise from non-target directions.
- **Neural beamforming**: ML-based, learns optimal spatial filtering.

Microphone arrays are used by Amazon Echo, Google Home, and enterprise conferencing systems. For a drive-through kiosk, even a 2-mic array with fixed beamforming would help.

### 3.3 Physical Enclosures & Windscreens

- Foam windscreens on the microphone reduce wind noise by 15-20 dB.
- A recessed microphone housing shields from rain and wind.
- Acoustic baffles around the speaker post reduce kitchen noise bleed.

---

## 4. Layer 2: Client-Side Audio Preprocessing (Browser)

This is the most impactful software layer for Brew since audio is captured in the browser before being sent to the server.

### 4.1 Option A: RNNoise (Open Source, Free)

**What it is:** A recurrent neural network for real-time noise suppression, originally by Xiph.org (creators of Opus codec). Compiled to WebAssembly for browser use.

**NPM packages:**
- `@shiguredo/rnnoise-wasm` (Apache 2.0)
- `@jitsi/rnnoise-wasm` (Apache 2.0, used by Jitsi Meet)
- `web-noise-suppressor` (MIT, wraps RNNoise for Web Audio API)

**How it would integrate with Brew:**
```
[Microphone] → [RNNoise AudioWorklet] → [hark VAD] → [Resample to 16kHz] → [WebSocket]
```

**Pros:**
- Free and open source
- Small WASM binary (~200KB)
- Low latency (~10ms frame processing)
- Proven in production (Jitsi Meet uses it for millions of calls)
- Runs in AudioWorklet (off main thread)

**Cons:**
- Trained on general noise; not specifically optimized for outdoor/drive-through
- Single-channel only (no spatial filtering)
- May suppress some speech if noise overlaps with speech frequencies

**Integration effort:** Medium. Requires adding an AudioWorklet node in the audio pipeline before the existing resampling step.

### 4.2 Option B: Picovoice Koala (Commercial, Privacy-Focused)

**What it is:** On-device noise suppression engine powered by deep learning. Processes audio entirely in the browser via WebAssembly.

**NPM package:** `@picovoice/koala-web`

**How it would integrate with Brew:**
```
[Microphone] → [Koala Worker] → [hark VAD] → [Resample to 16kHz] → [WebSocket]
```

**Pros:**
- Purpose-built for speech enhancement (trained specifically to preserve speech while removing noise)
- On-device processing (privacy-compliant)
- Works across Chrome, Safari, Firefox, Edge
- Processes 16-bit single-channel PCM (matches Brew's pipeline)

**Cons:**
- Requires an AccessKey (commercial license)
- Introduces processing delay (retrievable via `.delaySample`)
- ~2-5MB SDK size

**Integration effort:** Medium. Install npm package, create KoalaWorker, subscribe to WebVoiceProcessor.

### 4.3 Option C: Krisp SDK (Commercial, Enterprise-Grade)

**What it is:** The most robust JavaScript-based noise cancellation SDK for browsers. Used by major communication platforms. Offers noise cancellation + background voice cancellation (BVC).

**Key feature for drive-through:** **Background Voice Cancellation (BVC)** — specifically designed to filter out voices that are NOT the primary speaker. This directly addresses the multi-speaker problem in drive-throughs.

**How it would integrate with Brew:**
```
[Microphone (disable browser preprocessing)] → [Krisp filterNode] → [hark VAD] → [Resample] → [WebSocket]
```

**Important:** Krisp requires disabling the browser's built-in audio preprocessing:
```javascript
const stream = await navigator.mediaDevices.getUserMedia({
  audio: {
    echoCancellation: false,
    noiseSuppression: false,
    autoGainControl: false
  }
});
```

**Specs:**
- Frame processing: 1.5-2ms
- Memory: ~100MB
- Package size: 12MB
- Supported sample rates: 8kHz - 96kHz
- Processing in dedicated Web Workers (off main thread)

**Pros:**
- Best-in-class noise cancellation
- Background Voice Cancellation (BVC) — filters out non-primary speakers
- Inbound + outbound noise cancellation
- Enterprise support

**Cons:**
- Commercial license required (likely expensive for per-device deployment)
- 100MB memory footprint
- 12MB package size (impacts initial load)
- Must disable browser's built-in preprocessing (Krisp replaces it)

**Integration effort:** Medium-High. Requires SDK license, disabling browser defaults, inserting filter node.

### 4.4 Option D: Browser Built-in + Tuned hark

The simplest approach: rely on the browser's built-in noise suppression and tune the existing `hark` VAD.

**Current hark config in Brew:**
```javascript
const speechEvents = hark(stream, { interval: 100, threshold: -35, play: false });
```

**Tuning for noisy environments:**
- **Raise threshold** from `-35` to `-25` or `-20` dB. This requires louder audio to trigger "speaking" state, filtering out moderate background noise.
- **Use `volume_change` event** to dynamically monitor levels and auto-adjust threshold.
- **Increase interval** from `100ms` to `150-200ms` to reduce false positive rate.

**Additionally, explicitly enable browser preprocessing:**
```javascript
const stream = await navigator.mediaDevices.getUserMedia({
  audio: {
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true
  }
});
```

**Pros:** Zero additional dependencies, zero cost, immediate.
**Cons:** Limited effectiveness in truly noisy environments. Browser noise suppression varies by browser/OS.

---

## 5. Layer 3: Gemini Live API Configuration

The Gemini Live API has built-in VAD that can be configured for noisy environments. This is currently unused in Brew.

### 5.1 Configurable VAD via `realtime_input_config`

As of ADK PR #981 (merged June 2025), `RunConfig` supports `realtime_input_config` with the following VAD parameters:

```python
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.genai import types

run_config = RunConfig(
    streaming_mode=StreamingMode.BIDI,
    realtime_input_config=types.RealtimeInputConfig(
        automatic_activity_detection=types.AutomaticActivityDetection(
            # Lower sensitivity = less likely to trigger on background noise
            start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,

            # Lower end sensitivity = waits longer after speech before ending turn
            # (helps when customer pauses mid-order in noisy environment)
            end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,

            # Include 300ms of audio before detected speech start
            prefix_padding_ms=300,

            # Require 1500ms of silence before considering turn ended
            silence_duration_ms=1500,
        )
    ),
)
```

**Parameter explanations for drive-through:**

| Parameter | Recommended | Why |
|---|---|---|
| `start_of_speech_sensitivity` | `LOW` | Prevents engine rumble, wind, and background chatter from triggering speech detection |
| `end_of_speech_sensitivity` | `LOW` | Customers in drive-throughs often pause mid-sentence (looking at menu, talking to passengers). Low sensitivity gives them more time. |
| `prefix_padding_ms` | `300` | Captures the beginning of speech that might be clipped by delayed detection |
| `silence_duration_ms` | `1000-2000` | Longer silence requirement prevents premature turn-ending from brief pauses |

### 5.2 Manual Turn Control (Future)

The Gemini Live API also supports disabling automatic VAD entirely and using manual `ActivityStart`/`ActivityEnd` events. This would allow Brew to:

1. Use its own client-side VAD (hark or a better one) to detect speech.
2. Only send `ActivityStart` when confident a human is speaking.
3. Send `ActivityEnd` when speech stops.
4. Gemini only processes audio between these markers.

**Status:** The ADK does not yet fully support sending manual `ActivityStart`/`ActivityEnd` events through `LiveRequestQueue` (noted in PR #981 discussion). This is tracked as a future enhancement.

### 5.3 Configurable Turn Coverage

The Gemini Live API supports choosing whether to process ALL audio continuously or only audio when speech is detected. For noisy environments, processing only detected speech reduces the chance of noise being interpreted as commands.

---

## 6. Layer 4: Server-Side Audio Processing

If client-side preprocessing is insufficient, audio can be cleaned on the server before forwarding to Gemini.

### 6.1 Python-Based Noise Suppression

**Libraries:**
- **noisereduce** (`pip install noisereduce`): Spectral gating noise reduction. Can process 16kHz PCM chunks.
- **DeepFilterNet**: Deep learning-based noise suppression, state-of-the-art quality.
- **Silero VAD** (`pip install silero-vad`): Highly accurate voice activity detection that can gate audio before sending to Gemini.

**Architecture:**
```
[WebSocket receives PCM] → [Silero VAD: is this speech?]
    → YES → [noisereduce/DeepFilterNet: clean audio] → [Send to Gemini]
    → NO  → [Drop chunk, don't send to Gemini]
```

**Pros:**
- Full control over audio processing.
- Can use more powerful models than browser WASM allows.
- Silero VAD is extremely accurate (better than hark for noisy environments).

**Cons:**
- Adds latency (processing time + buffering).
- Increases server CPU/memory usage.
- Complicates the real-time streaming pipeline.
- Must be careful not to break the PCM stream expected by Gemini.

### 6.2 Audio Buffering Strategy

Instead of streaming every chunk to Gemini, buffer audio and only forward when confident speech is present:

1. Accumulate 500ms of audio.
2. Run Silero VAD on the buffer.
3. If speech detected, forward the buffer + continue streaming.
4. If no speech, discard the buffer.

This prevents noise-only audio from ever reaching Gemini, reducing false triggers and API costs.

---

## 7. Layer 5: Prompt Engineering & Agent Behavior

The system prompt already has some noise handling, but it can be strengthened.

### 7.1 Current Prompt Provisions

The system prompt already includes:
- **Anti-hallucination rule**: Ignores background noise that sounds like foreign languages.
- **Interruption handling**: Stays silent on noise-only interrupts.

### 7.2 Potential Prompt Enhancements

Additional instructions that could help:

```
NOISY ENVIRONMENT PROTOCOL:
- You are deployed in a drive-through with significant background noise (engines, wind, other cars, passengers).
- If you hear unclear, garbled, or very short utterances that don't form a coherent request, ask: "Sorry, I didn't catch that. Could you repeat?"
- NEVER guess at an order from unclear audio. Always confirm before adding items.
- If you hear what sounds like a side conversation between passengers (e.g., "what do you want?" / "I don't know"), do NOT treat it as an order. Wait for the customer to address you directly.
- If you hear overlapping voices, respond ONLY to the voice that seems to be addressing you (typically the clearest/loudest voice near the microphone).
- Use confirmation more aggressively: after every item, briefly confirm what you heard before adding it.
```

### 7.3 Confidence-Based Confirmation

Instead of immediately adding items from unclear audio, the agent could adopt a two-pass approach:
1. Hear the request.
2. Confirm: "I heard a Grande Iced Latte — is that right?"
3. Only call `add_item` after confirmation.

This is slower but dramatically reduces errors in noisy environments.

---

## 8. Layer 6: Speaker Diarization (Multi-Speaker)

When multiple people are talking (passengers in a car), the system needs to identify WHO is the customer placing the order.

### 8.1 The Challenge

In a drive-through:
- The driver is typically the one ordering.
- Passengers may be discussing what they want ("Should we get fries?").
- Children may be talking/crying in the background.
- The system should only respond to the person actively ordering.

### 8.2 Available Technologies

**Real-time speaker diarization frameworks:**

| Solution | Latency | Approach | Browser? |
|---|---|---|---|
| **diart** (Python) | Real-time | Streaming diarization | Server-side |
| **WhisperLiveKit** | Real-time | Whisper + Sortformer diarization | Server-side via WebSocket |
| **Sortformer2.1** | Low-latency | Neural speaker diarization | Server-side |
| **Krisp BVC** | Real-time | Background voice cancellation | Browser-side |

### 8.3 Practical Approaches for Brew

**Approach A: Krisp Background Voice Cancellation (Simplest)**
Krisp's BVC feature specifically filters out voices that are not the primary speaker (closest to the microphone). This is the simplest solution for the multi-speaker problem — it doesn't identify speakers, it just removes non-primary voices.

**Approach B: Proximity-Based Filtering (Hardware)**
Use a directional microphone aimed at the driver's window. Physics does the filtering — the closest speaker (the customer) is naturally louder and more direct.

**Approach C: Server-Side Diarization (Most Complex)**
Run a diarization model on the server to label audio segments by speaker. Only forward "Speaker 1" (the primary speaker) audio to Gemini. This is technically possible but adds significant latency and complexity.

**Approach D: Prompt-Based Handling (Simplest, Least Reliable)**
Instruct the agent via prompt to ignore side conversations and only respond to direct order commands. Already partially implemented in Brew's system prompt.

### 8.4 Recommendation

For Brew, the practical order of implementation should be:
1. **Hardware** (directional mic) — most effective, simplest.
2. **Krisp BVC** — if software-only solution needed.
3. **Prompt engineering** — already partially done, can be enhanced.
4. **Server-side diarization** — only if the above are insufficient.

---

## 9. What Industry Leaders Do

### Lilac Labs (YC-backed, drive-through specialist)
- **95%+ order accuracy** in noisy drive-through environments.
- Uses advanced audio processing specifically trained on drive-through audio (not general speech).
- Filters engine noise, background conversations, and environmental sounds.
- Integrates with existing drive-through hardware (Panasonic, HME, Delphi).
- Seamless handoff to human staff for complex/unclear situations.

### Amazon Nova Sonic (AWS drive-through solution)
- Engineered for streaming speech recognition across accents.
- Built-in robustness to background noise common in drive-through settings.
- Dynamic menu display integration.

### Wendy's FreshAI (Google Cloud partnership)
- Reduced service times by 22 seconds vs regional averages.
- Uses custom-trained models for drive-through-specific vocabulary.
- Human fallback for low-confidence interactions.

### Taco Bell Voice AI
- Expanded across 13 states after successful pilots.
- Handles complex menu with modifiers and combos.
- Uses confidence scoring to decide when to ask for clarification vs. proceed.

### Common Patterns Across All Leaders:
1. **Specialized audio preprocessing** — not generic noise suppression.
2. **Drive-through-specific training data** — models trained on actual drive-through recordings.
3. **Human fallback** — always have a way to escalate to a human.
4. **Confirmation loops** — verify unclear orders before committing.
5. **Hardware integration** — work with existing drive-through speaker systems.

---

## 10. Recommended Implementation Roadmap

### Phase 1: Quick Wins (No New Dependencies)

**Effort: Low | Impact: Medium**

1. **Tune hark VAD threshold**: Raise from `-35` to `-25` dB.
2. **Configure Gemini VAD**: Add `realtime_input_config` to `RunConfig` with `START_SENSITIVITY_LOW` and `END_SENSITIVITY_LOW`.
3. **Enhance system prompt**: Add noisy environment protocol (Section 7.2).
4. **Explicitly set browser audio constraints**: Ensure `noiseSuppression: true`, `echoCancellation: true`.

### Phase 2: Client-Side Noise Suppression (1-2 Weeks)

**Effort: Medium | Impact: High**

1. **Integrate RNNoise** (`web-noise-suppressor` or `@shiguredo/rnnoise-wasm`) into the audio pipeline as an AudioWorklet node before resampling.
2. **A/B test** with and without noise suppression in a real drive-through environment.
3. **Monitor** Gemini API error rates and order accuracy.

### Phase 3: Advanced VAD & Gating (2-3 Weeks)

**Effort: Medium-High | Impact: High**

1. **Replace hark with Silero VAD** on the server side for more accurate speech detection.
2. **Implement audio gating**: Only forward audio chunks to Gemini when speech is confidently detected.
3. **Add dynamic threshold adjustment**: Monitor ambient noise level and auto-adjust VAD sensitivity.

### Phase 4: Enterprise Solutions (If Needed)

**Effort: High | Impact: Very High**

1. **Evaluate Krisp SDK** for background voice cancellation (multi-speaker filtering).
2. **Evaluate Picovoice Koala** for speech-optimized noise suppression.
3. **Consider hardware upgrades**: Directional microphones, windscreens, acoustic enclosures.
4. **Implement human fallback**: Route to human operator when confidence is low.

---

## 11. Cost & Complexity Comparison

| Solution | Cost | Latency Added | Browser Size Impact | Effectiveness | Multi-Speaker? |
|---|---|---|---|---|---|
| Tune hark + Gemini VAD | Free | 0ms | 0 | Low-Medium | No |
| RNNoise (WASM) | Free | ~10ms | ~200KB | Medium | No |
| Picovoice Koala | Commercial | ~20ms | ~2-5MB | Medium-High | No |
| Krisp SDK | Commercial | ~2ms | ~12MB (+100MB RAM) | High | Yes (BVC) |
| Server-side Silero VAD | Free | ~50-100ms | 0 | Medium-High | No |
| Server-side DeepFilterNet | Free | ~50-100ms | 0 | High | No |
| Directional Mic (hardware) | $150-300 | 0ms | 0 | Very High | Partial |
| Full diarization pipeline | Free/Commercial | 200-500ms | 0 | High | Yes |

---

## 12. References

1. **Krisp Browser SDK**: https://sdk-docs.krisp.ai/docs/introduction
2. **Picovoice Koala Web**: https://picovoice.ai/docs/api/koala-web/
3. **RNNoise WASM (Jitsi)**: https://github.com/jitsi/rnnoise-wasm
4. **web-noise-suppressor**: https://github.com/sapphi-red/web-noise-suppressor
5. **Gemini Live API Guide**: https://ai.google.dev/gemini-api/docs/live-guide
6. **Gemini Live API VAD Config**: https://ai.google.dev/gemini-api/docs/live#configure-automatic-vad
7. **ADK RunConfig realtime_input_config PR**: https://github.com/google/adk-python/pull/981
8. **ADK VAD Configuration Issue**: https://github.com/google/adk-python/issues/517
9. **Lilac Labs Drive-Thru AI**: https://www.lilaclabs.ai/solutions/drive-thru
10. **Amazon Nova Sonic Drive-Thru**: https://aws.amazon.com/blogs/machine-learning/voice-ai-powered-drive-thru-ordering-with-amazon-nova-sonic-and-dynamic-menu-displays/
11. **hark npm (VAD)**: https://www.npmjs.com/package/hark
12. **diart (Speaker Diarization)**: https://diart.readthedocs.io/en/stable/
13. **Panasonic Attune II**: https://connect.na.panasonic.com/restaurant-retail/drive-thru/attune-ii-drive-thru-communication-system
14. **Silero VAD**: https://github.com/snakers4/silero-vad
15. **Gemini Live API Drive-Thru Tutorial**: https://getstream.io/blog/drive-thru-voice-ai/
