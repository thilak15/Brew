---
title: "Brew: I Built a Real-Time Voice AI Drive-Thru Barista with Gemini Live API and Google ADK"
published: false
description: "How I built a voice-first AI ordering agent for coffee shop drive-thrus using Gemini 2.5 Flash Native Audio, Google Agent Development Kit, Cloud Run, and Firestore — for the Gemini Live Agent Challenge hackathon."
tags: googlecloud, gemini, ai, hackathon
cover_image: https://raw.githubusercontent.com/thilak15/Brew/main/docs/architecture.png
---

> **Disclosure:** I created this blog post and the Brew project for the purposes of entering the [Gemini Live Agent Challenge](https://googleai.devpost.com/) hackathon. #GeminiLiveAgentChallenge

---

## TL;DR

I built **Brew** — a real-time, voice-first AI ordering system for coffee shop drive-thrus. Customers talk to an AI barista through their microphone, and it takes their order through natural conversation. No buttons, no typing, just speech. The AI listens, understands complex orders with modifiers, handles interruptions, and updates a live on-screen menu and receipt as the conversation flows.

**GitHub:** [github.com/thilak15/Brew](https://github.com/thilak15/Brew)

---

## The Problem I Wanted to Solve

Traditional drive-thru ordering is broken. Long wait times, order inaccuracies, and staffing challenges plague the industry. Human operators handle one car at a time, miscommunication leads to wrong orders, and during peak hours, lines stretch around the block.

I wanted to see if a live voice AI agent could do this better — not a chatbot with text-to-speech bolted on, but a genuinely conversational agent that handles the full complexity of real ordering: sizes, modifiers, corrections, interruptions, and multi-item requests.

---

## What Brew Does

Brew replaces the human operator at a drive-thru speaker box with an AI barista. Here's what it handles:

- **Natural speech understanding** — "Can I get a grande iced latte with oat milk and an extra shot?" works exactly as you'd expect
- **Interruptions (barge-in)** — Change your mind mid-sentence. The AI stops speaking and listens
- **Real-time UI updates** — The menu highlights relevant categories and the receipt builds live as items are confirmed
- **Complex order management** — Modifiers (syrups, milk swaps, toppings, ice levels, warming), undo, batch operations, and running totals
- **Multilingual support** — Speak in Spanish, Hindi, or any language Gemini understands, and the agent mirrors your language automatically
- **Session persistence** — Cart state survives Cloud Run instance restarts via Firestore

The menu has 22 items across 3 categories (Drinks, Breakfast, Desserts) with a full modifier system.

---

## The Tech Stack — All Google AI and Cloud

This project is built end-to-end on Google's AI and Cloud platform. Here's every piece:

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **AI Model** | Gemini 2.5 Flash Native Audio | Real-time voice conversation with function calling |
| **Agent Framework** | Google Agent Development Kit (ADK) | Agent orchestration, tool management, live streaming |
| **Backend** | Python 3.11, FastAPI | WebSocket server, session management |
| **Frontend** | Next.js 14, React 18, TypeScript | Dynamic UI with real-time state updates |
| **Audio** | Web Audio API (AudioWorklet) | Low-latency audio capture and playback |
| **Transport** | WebSockets | Bidirectional PCM audio + JSON state streaming |
| **Session Persistence** | Google Cloud Firestore | Cart state across instances |
| **Deployment** | Google Cloud Run | Serverless containers for backend and frontend |
| **Container Registry** | Google Artifact Registry | Docker image storage |
| **CI/CD** | GitHub Actions + Workload Identity Federation | Keyless automated deployment to GCP |

---

## How I Built It — Architecture Deep Dive

The system has four layers:

### 1. Browser (Customer Device)

The Next.js frontend captures microphone audio via the Web Audio API using an `AudioWorklet` processor. Raw PCM audio at 16kHz streams to the backend over a WebSocket. The frontend receives two things back: audio response bytes (played through another AudioWorklet) and JSON state updates that drive the UI.

Three main components power the interface:
- **SmartMenu** — A dynamic tabbed menu that auto-switches categories (ordering a "Cake Pop" flips the view to Desserts)
- **LiveReceipt** — A real-time order panel showing items, modifiers, and a running price total
- **AudioVisualizer** — Visual feedback during the conversation

### 2. Backend Server (Cloud Run)

A Python/FastAPI WebSocket server running on Cloud Run. It manages the bidirectional audio stream between the browser and Gemini. The key responsibilities:

- Hosts the ADK `Runner` that orchestrates the agent lifecycle
- Implements a **tool gate mechanism** — blocks user audio while the AI executes tool calls, preventing race conditions where the model hears its own confirmations
- Handles upstream (browser → Gemini) and downstream (Gemini → browser) as concurrent async tasks
- Proactive session reconnection before the 10-minute Live API hard limit

### 3. Agent Layer (Google ADK)

The agent is defined using Google's Agent Development Kit with **14 tools** for order management:

```python
root_agent = Agent(
    name="brew_agent",
    model="gemini-2.5-flash-native-audio-preview-12-2025",
    description="Drive-thru barista that takes beverage orders with modifiers.",
    instruction=get_system_prompt(),
    tools=[
        add_item, add_items,
        remove_item, remove_items,
        add_modifier, add_modifiers,
        remove_modifier, set_modifier,
        set_ice_level, undo_last_change,
        clear_order, set_menu_view,
        get_order_summary,
    ],
)
```

ADK's `run_live()` method establishes a persistent bidirectional stream with the Gemini Live API. Tools are plain Python functions with detailed docstrings that the model uses for function calling.

### 4. AI Model (Gemini Live API)

The `gemini-2.5-flash-native-audio-preview-12-2025` model handles everything in a single streaming session: receives raw audio, processes speech, decides when to call tools, and generates spoken responses. The system prompt injects the full menu (items, prices, sizes, modifiers) so the model is grounded in real data.

### Data Flow

```
Customer speaks into mic
  → Browser captures PCM audio via AudioWorklet
  → WebSocket sends binary audio frames to backend
  → Backend forwards audio to Gemini via ADK run_live()
  → Gemini processes speech, decides to call tools or respond
  → If tool call: ADK executes tool → updates OrderState → syncs to Firestore
  → Gemini generates audio response
  → Backend streams audio bytes back over WebSocket
  → Browser plays audio via AudioWorklet
  → Backend sends JSON order state updates
  → Frontend re-renders SmartMenu + LiveReceipt in real time
```

---

## Google Cloud Services in Detail

### Gemini Live API (via Google GenAI SDK)

This is the core of Brew. The Live API provides native audio streaming — the model receives raw audio and produces audio responses directly, without separate speech-to-text or text-to-speech steps. Combined with function calling, this means the model can hear "add oat milk to both drinks," call the `add_modifiers` batch tool, and speak a confirmation — all in one streaming session with sub-second latency.

### Google Agent Development Kit (ADK)

ADK handles the agent lifecycle. The `run_live()` method manages the persistent WebSocket connection to Gemini, routes tool calls to my Python functions, and handles the back-and-forth of a multi-turn conversation. I defined 14 tools with detailed docstrings, and ADK + Gemini handle the rest.

### Cloud Run

Both the backend (FastAPI) and frontend (Next.js) are deployed as separate Cloud Run services. Session affinity is critical for WebSocket connections — without it, requests hit different instances that don't have the session state.

### Firestore

Cart state is persisted to Firestore after every order change. This means if Cloud Run scales horizontally or an instance restarts, the customer's order survives. I built a custom `FirestoreSessionService` that wraps ADK's `InMemorySessionService` with Firestore persistence.

### Artifact Registry + Workload Identity Federation

Docker images are stored in Artifact Registry. CI/CD uses Workload Identity Federation for keyless authentication from GitHub Actions to GCP — no service account keys stored anywhere.

---

## Hard Problems I Solved

### 1. The Tool Gate Problem

Without intervention, the model would hear its own tool-call confirmations as user input, creating infinite loops. I implemented a tool gate that blocks user audio forwarding while the AI is executing tools. This was the single most impactful fix for reliability.

### 2. The 10-Minute Session Limit

The Gemini Live API has a hard 10-minute session limit. Brew proactively reconnects at 8 minutes, injecting the current order context into the new session so the AI seamlessly continues the conversation without re-greeting the customer.

### 3. Model Hallucinating Tool Arguments

Native audio models sometimes hallucinate tool arguments — inventing item IDs that don't exist. I switched from UUIDs to sequential integer IDs (`item_1`, `item_2`, ...) which dramatically reduced hallucination. I also added `_resolve_item_id()` that handles numeric shorthand and positional references.

### 4. Batch Operations for Latency

Without batch tools, the model makes sequential tool calls with separate confirmations for each item in a multi-item order. I added `add_items`, `remove_items`, and `add_modifiers` batch tools that handle everything in a single call, cutting latency significantly.

### 5. Idempotency Guards

The model sometimes retries tool calls during transient errors. Without idempotency guards, this would add duplicate modifiers. Every `add_modifier` call checks for existing identical modifiers before applying.

---

## Key Learnings

1. **Tool docstrings are the primary interface.** Clear, specific docstrings with examples produce dramatically better tool-calling accuracy than vague descriptions. I iterated on these more than any other part of the codebase.

2. **AudioWorklet is non-negotiable.** The deprecated `ScriptProcessorNode` introduces unpredictable latency. AudioWorklet provides consistent low-latency audio processing.

3. **Session affinity on Cloud Run is essential** for WebSocket connections. Without it, subsequent requests hit different instances.

4. **Native audio models behave differently than text models.** They're more prone to hallucinating tool arguments, more sensitive to background noise, and need explicit instructions about when NOT to respond (e.g., to background noise or their own echoes).

5. **Firestore for session persistence is a perfect fit** for serverless deployments. The read/write latency is low enough that it doesn't impact the real-time experience.

---

## Running It Yourself

Brew is fully open source. You can run it locally with Docker:

```bash
git clone https://github.com/thilak15/Brew.git
cd Brew
cp backend/.env.example backend/.env
# Add your GOOGLE_API_KEY to backend/.env
docker compose up -d --build
```

Then open `http://localhost:3000` in Chrome, click "Drive Up," allow mic access, and start ordering.

**GitHub:** [github.com/thilak15/Brew](https://github.com/thilak15/Brew)

---

## What's Next

**Menu-agnostic deployment.** The menu loads from a JSON file. Swap it out, and Brew becomes a taco shop, a pizza place, or a pharmacy pickup counter. The next step is a pipeline that takes any restaurant's menu and auto-generates a ready-to-deploy voice ordering agent.

**Multilingual real-time language switching.** Gemini's native audio model already understands multiple languages. The goal is automatic language detection mid-conversation — if a customer starts in English and switches to Spanish, the agent follows without any button press.

The hard part was proving that a live voice agent can handle complex, modifier-heavy ordering with interruptions, corrections, and batch operations — correctly and reliably. That's done. Now it's about making it work for anyone, in any language.

---

*This project was created for the [Gemini Live Agent Challenge](https://googleai.devpost.com/) hackathon. #GeminiLiveAgentChallenge*

*Built by [Thilak Daggula](https://github.com/thilak15)*
