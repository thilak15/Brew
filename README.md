<p align="center">
  <h1 align="center">Brew</h1>
  <p align="center"><strong>AI-Powered Voice Drive-Thru Ordering Agent</strong></p>
  <p align="center">A real-time conversational AI barista built with Google's Gemini Live API, Agent Development Kit, and Cloud Run.</p>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> |
  <a href="#architecture">Architecture</a> |
  <a href="#google-cloud-deployment">Cloud Deployment</a> |
  <a href="#demo-video">Demo</a> |
  <a href="#whats-next-for-brew">What's Next</a>
</p>

---

## What is Brew?

Brew is a **real-time, voice-first AI ordering system** for coffee shop drive-thrus. Customers interact with a conversational AI agent that takes their order through natural speech -- just like talking to a real person at the speaker box.

The AI listens, understands, and processes orders in real time. It dynamically updates the on-screen menu and receipt as the conversation flows. No buttons, no typing -- just talk.

**Category:** Live Agents -- Real-time Interaction (Audio/Vision)

### The Problem

Traditional drive-thru ordering suffers from long wait times, order inaccuracies, and staffing challenges. Human operators handle one car at a time, and miscommunication leads to wrong orders. During peak hours, lines stretch around the block.

### The Solution

Brew replaces the human operator with an AI barista that:

- **Understands natural speech** -- Customers order exactly how they would with a human: "Can I get a grande iced latte with oat milk and an extra shot?"
- **Handles interruptions gracefully** -- Barge-in support lets customers change their mind mid-sentence without waiting for the AI to finish speaking
- **Updates the UI in real time** -- The menu highlights relevant categories and the receipt builds live as items are confirmed
- **Manages complex orders** -- Supports modifiers (syrups, milk swaps, toppings, ice levels, warming), undo, batch operations, and order summaries with running totals
- **Persists state across connections** -- Cart state is synced to Firestore, surviving Cloud Run instance restarts and horizontal scaling

---

## Demo Video

> [Link to demo video on YouTube]

---

## Key Features

### Voice-First Conversational Ordering
- Natural bidirectional conversation using Gemini's native audio model (`gemini-2.5-flash-native-audio-preview-12-2025`)
- Ultra-low-latency voice interactions via the Gemini Live API with simultaneous listen-and-speak
- Barge-in (interruption) support -- the AI stops speaking when the customer starts talking
- Distinct barista persona with friendly, concise responses

### Smart Dynamic Menu
- 3 menu categories with 22 items: Drinks (12), Breakfast (5), Desserts (5)
- Auto-switching tabs -- ordering a "Cake Pop" automatically switches the menu view to Desserts
- Optimized WebP thumbnail images for each menu item

### Live Order Receipt
- Real-time order panel that updates instantly as the AI confirms items
- Full modifier display: syrups, milk swaps, toppings, ice levels, warming
- Running price total that updates dynamically with each addition or removal

### Intelligent Order Management
- **Context-aware understanding** -- handles "make that iced instead", "actually remove the last one", "add oat milk to both drinks"
- **Batch operations** -- `add_items`, `remove_items`, and `add_modifiers` tools handle multi-item requests in a single call
- **Modifier detection** -- parses intent like "I'm vegan" and auto-suggests oat milk alternatives
- **Undo support** -- "go back" or "undo" reverts the last change
- **Upselling** -- asks about warming for food items, size preferences for drinks

### Robust Error Handling
- Automatic reconnection with exponential backoff on transient Gemini API errors (1007, 1008, 1011)
- Proactive session reconnection before the 10-minute Live API hard limit
- Order context injection after reconnects so the AI never loses track of the conversation
- Idempotency guards prevent duplicate items from tool-calling loops

---

## Architecture

<p align="center">
  <img src="docs/architecture.png" alt="Brew Architecture Diagram" width="800" />
</p>

### System Design

The system has four layers:

**1. Browser (Customer Device)**
- Next.js 14 frontend captures microphone audio via the Web Audio API (AudioWorklet)
- Raw PCM audio at 16kHz is streamed to the backend over a WebSocket connection
- The frontend receives audio responses (played back via AudioWorklet) and JSON state updates (order changes, menu context switches, error signals)
- Three main UI components: `SmartMenu` (dynamic tabbed menu), `LiveReceipt` (real-time order panel), and `AudioVisualizer` (visual feedback during conversation)

**2. Backend Server (Cloud Run)**
- Python 3.11 / FastAPI WebSocket server running on Google Cloud Run
- Manages the bidirectional audio stream between the browser and the Gemini Live API
- Hosts the ADK `Runner` which orchestrates the agent lifecycle, tool execution, and session management
- Implements a tool gate mechanism that blocks user audio input while the AI is executing tool calls, preventing race conditions
- Handles upstream (browser to Gemini) and downstream (Gemini to browser) data flow as concurrent async tasks

**3. Agent Layer (Google ADK)**
- The agent is defined using Google's Agent Development Kit (ADK) with 14 tools for order management
- ADK's `run_live()` method establishes a persistent bidirectional stream with the Gemini Live API
- Tools are plain Python functions with docstrings that the model uses for function calling:
  - `add_item` / `add_items` -- add single or batch items to the order
  - `remove_item` / `remove_items` -- remove single or batch items
  - `add_modifier` / `add_modifiers` -- apply modifiers (syrups, milk swaps, toppings, ice levels, warming)
  - `remove_modifier` / `set_modifier` -- remove or replace modifiers
  - `set_ice_level` -- set ice level for a drink
  - `undo_last_change` -- revert the last order change
  - `clear_order` -- clear the entire order
  - `set_menu_view` -- switch the visual menu tab on the customer's screen
  - `get_order_summary` -- generate a summary with itemized prices

**4. AI Model (Gemini Live API)**
- Uses `gemini-2.5-flash-native-audio-preview-12-2025` for native audio input/output with function calling
- The model receives raw audio, processes speech, decides when to call tools, and generates spoken responses -- all in a single streaming session
- System prompt injects the full menu (items, prices, sizes, modifiers) so the model is grounded in real data

### Data Flow

```
Customer speaks into mic
    --> Browser captures PCM audio via AudioWorklet
    --> WebSocket sends binary audio frames to backend
    --> Backend forwards audio to Gemini via ADK run_live()
    --> Gemini processes speech, decides to call tools or respond
    --> If tool call: ADK executes tool --> updates OrderState --> syncs to Firestore
    --> Gemini generates audio response
    --> Backend streams audio bytes back over WebSocket
    --> Browser plays audio via AudioWorklet
    --> Backend sends JSON order state updates
    --> Frontend re-renders SmartMenu + LiveReceipt in real time
```

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **AI Model** | Gemini 2.5 Flash (Native Audio, 12-2025) | Real-time voice conversation with function calling |
| **Agent Framework** | Google Agent Development Kit (ADK) | Agent orchestration, tool management, live streaming |
| **Backend** | Python 3.11, FastAPI | WebSocket server, session management, order state |
| **Frontend** | Next.js 14, React 18, TypeScript | Dynamic UI with real-time state updates |
| **Audio** | Web Audio API (AudioWorklet) | Low-latency audio capture and playback in browser |
| **Transport** | WebSockets (bidirectional) | Real-time PCM audio + JSON state streaming |
| **Session Persistence** | Google Cloud Firestore | Cart state survives instance restarts and scaling |
| **Deployment** | Google Cloud Run | Serverless container hosting for backend and frontend |
| **Container Registry** | Google Artifact Registry | Docker image storage |
| **CI/CD** | GitHub Actions | Automated deployment on push to main |
| **Containerization** | Docker, Docker Compose | Reproducible local and cloud builds |
| **Auth (CI/CD)** | Workload Identity Federation | Keyless authentication from GitHub Actions to GCP |

---

## Google Cloud Services Used

| Service | How Brew Uses It |
|---------|-----------------|
| **Gemini Live API** (via Google GenAI SDK) | Native audio streaming for real-time voice conversation and function calling |
| **Cloud Run** | Hosts both the backend (FastAPI) and frontend (Next.js) as serverless containers |
| **Firestore** | Persists cart state across Cloud Run instances for session continuity |
| **Artifact Registry** | Stores Docker images built by CI/CD pipeline |
| **IAM + Workload Identity Federation** | Keyless authentication from GitHub Actions to GCP for automated deployments |

---

## Google Cloud Deployment

Brew's backend and frontend are deployed as separate Cloud Run services. Every push to `main` triggers an automated deployment via GitHub Actions.

### Proof of Cloud Deployment

The following files demonstrate Brew running on Google Cloud:

- **[`.github/workflows/deploy.yml`](.github/workflows/deploy.yml)** -- GitHub Actions workflow that builds Docker images, pushes to Artifact Registry, and deploys both services to Cloud Run
- **[`deploy.sh`](deploy.sh)** -- Manual deployment script that performs the same steps via `gcloud` CLI
- **[`setup-gcp.sh`](setup-gcp.sh)** -- One-time GCP setup script that creates the service account, Workload Identity Federation pool, and Artifact Registry
- **[`backend/firestore_session_service.py`](backend/firestore_session_service.py)** -- Firestore-backed session service for ADK session persistence on Cloud Run
- **[`backend/order_state.py`](backend/order_state.py)** -- Order state manager with async Firestore sync for cart persistence across instances

### Automated CI/CD Pipeline

The deployment is fully automated using GitHub Actions with Workload Identity Federation (keyless auth):

```
Push to main
  --> GitHub Actions triggers deploy.yml
  --> Authenticates to GCP via Workload Identity Federation (no service account keys)
  --> Builds backend Docker image, pushes to Artifact Registry
  --> Deploys backend to Cloud Run with env vars (GOOGLE_API_KEY, model config)
  --> Retrieves backend URL, derives WebSocket URL
  --> Builds frontend Docker image with backend WSS URL baked in
  --> Pushes frontend image to Artifact Registry
  --> Deploys frontend to Cloud Run
```

---

## Quick Start

### Prerequisites

- **Docker** and **Docker Compose** installed ([Get Docker](https://docs.docker.com/get-docker/))
- A **Google API Key** from [Google AI Studio](https://aistudio.google.com/apikey)

### 1. Clone the Repository

```bash
git clone https://github.com/thilak15/Brew.git
cd Brew
```

### 2. Set Up Environment Variables

```bash
cp backend/.env.example backend/.env
```

Open `backend/.env` and add your API key:

```env
GOOGLE_GENAI_USE_VERTEXAI=FALSE
GOOGLE_API_KEY=your_api_key_here
BREW_AGENT_MODEL=gemini-2.5-flash-native-audio-preview-12-2025
```

### 3. Build and Run

```bash
docker compose up -d --build
```

This builds and starts both containers:
- **Frontend**: http://localhost:3000
- **Backend**: http://localhost:8000

### 4. Start Ordering

1. Open http://localhost:3000 in Chrome (recommended for best audio support)
2. Click **"Drive Up"** to start a new session
3. Allow microphone access when prompted
4. Start speaking -- try: *"Hi, can I get a grande iced latte with oat milk?"*

### Stopping

```bash
docker compose down
```

<details>
<summary><strong>Manual Local Setup (without Docker)</strong></summary>

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Add your GOOGLE_API_KEY to .env
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
echo "NEXT_PUBLIC_WS_URL=ws://localhost:8000" > .env.local
npm run dev
```

</details>

<details>
<summary><strong>Deploy to Google Cloud Run</strong></summary>

### One-Time Setup

**1. Install gcloud CLI:**
```bash
brew install --cask google-cloud-sdk   # macOS
```

**2. Authenticate:**
```bash
gcloud auth login
```

**3. Run the setup script** (creates service account, Workload Identity Federation, Artifact Registry):
```bash
./setup-gcp.sh --project YOUR_PROJECT_ID --repo your-username/Brew
```

**4. Add GitHub Secrets** -- the script prints 4 values to add at your repo's Settings > Secrets > Actions:

| Secret | Value |
|--------|-------|
| `GCP_PROJECT_ID` | Your GCP project ID |
| `WIF_PROVIDER` | Printed by setup script |
| `WIF_SERVICE_ACCOUNT` | Printed by setup script |
| `GOOGLE_API_KEY` | Your Google AI Studio API key |

Now every push to `main` will automatically build and deploy both services to Cloud Run.

### Manual Deploy (without CI/CD)

```bash
./deploy.sh --project YOUR_PROJECT_ID --api-key YOUR_API_KEY
```

### Tear Down

```bash
gcloud run services delete brew-frontend --region us-central1 --quiet
gcloud run services delete brew-backend --region us-central1 --quiet
```

</details>

---

## Project Structure

```
Brew/
├── backend/
│   ├── main.py                    # FastAPI WebSocket server, ADK run_live() orchestration
│   ├── agent.py                   # Google ADK agent with 14 order management tools
│   ├── order_state.py             # Per-session order state with Firestore persistence
│   ├── menu.py                    # Menu loader, system prompt builder, item validation
│   ├── menu.json                  # Full menu data: drinks, breakfast, desserts, modifiers
│   ├── firestore_session_service.py  # Firestore-backed ADK session service for Cloud Run
│   ├── system_prompt.md           # System prompt for standard models
│   ├── system_prompt_09.md        # System prompt tuned for native-audio models
│   ├── requirements.txt           # Python dependencies
│   ├── Dockerfile                 # Backend container
│   └── .env.example               # Environment variable template
├── frontend/
│   ├── app/
│   │   ├── page.tsx               # Main page: session management, mic capture, UI layout
│   │   ├── layout.tsx             # Root layout with fonts and metadata
│   │   └── globals.css            # Global styles
│   ├── components/
│   │   ├── SmartMenu.tsx          # Dynamic tabbed menu with auto-switching categories
│   │   ├── LiveReceipt.tsx        # Real-time order receipt with modifier display
│   │   └── AudioVisualizer.tsx    # Visual feedback during voice conversation
│   ├── lib/
│   │   ├── useBrewWebSocket.ts    # WebSocket hook for real-time communication
│   │   ├── audioPipeline.ts       # AudioWorklet-based mic capture and playback
│   │   ├── orderReducer.ts        # State management for order updates
│   │   └── backendUrl.ts          # Backend URL resolution helper
│   ├── public/
│   │   ├── audio-processor.js     # AudioWorklet processor for PCM audio
│   │   └── images/menu/           # Optimized WebP menu item thumbnails
│   ├── Dockerfile                 # Frontend container (standalone Next.js build)
│   └── .env.local.example         # Frontend env template
├── .github/
│   └── workflows/
│       └── deploy.yml             # CI/CD: GitHub Actions to Cloud Run
├── docs/
│   └── architecture.png           # System architecture diagram
├── scripts/
│   └── generate_menu_images.py    # Image generation script (Imagen 3 via Gemini API)
├── docker-compose.yml             # Local orchestration for both services
├── deploy.sh                      # Manual GCP Cloud Run deployment script
├── setup-gcp.sh                   # One-time GCP setup for CI/CD
└── README.md
```

---

## Menu

| Category | Items |
|----------|-------|
| **Drinks** (12) | Iced Latte, Hot Latte, Caramel Macchiato, Mocha, Chai Latte, Matcha Latte, Cold Brew, Americano, Cappuccino, Frappuccino, Shaken Espresso, Brown Sugar Shaken Espresso |
| **Breakfast** (5) | Bacon & Gouda Sandwich, Spinach Feta Wrap, Ham & Swiss Croissant, Egg Bites, Butter Croissant |
| **Desserts** (5) | Chocolate Chip Cookie, Fudge Brownie, Blueberry Muffin, Lemon Loaf, Cake Pop |
| **Modifiers** | Syrups (Vanilla, Caramel, SF Vanilla, Hazelnut, Mocha), Milk Swaps (Oat, Almond, Soy, Whole, Nonfat), Toppings (Whipped Cream, Cold Foam, Matcha Cold Foam, Caramel Drizzle, Cinnamon), Ice Levels (Light, Normal, Extra, No Ice), Warming |

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_API_KEY` | Yes | API key from [Google AI Studio](https://aistudio.google.com/apikey) |
| `GOOGLE_GENAI_USE_VERTEXAI` | Yes | Set to `FALSE` to use the Gemini API directly |
| `BREW_AGENT_MODEL` | No | AI model override (default: `gemini-2.5-flash-native-audio-preview-12-2025`) |
| `GCP_PROJECT_ID` | No | GCP project ID for Firestore cart persistence |

---

## Third-Party Integrations

| Integration | License | Purpose |
|-------------|---------|---------|
| [Google GenAI SDK](https://github.com/google/generative-ai-python) | Apache 2.0 | Gemini API client |
| [Google Agent Development Kit (ADK)](https://github.com/google/adk-python) | Apache 2.0 | Agent framework with live streaming |
| [FastAPI](https://github.com/tiangolo/fastapi) | MIT | Backend web framework |
| [Next.js](https://github.com/vercel/next.js) | MIT | Frontend React framework |
| [hark](https://github.com/otalk/hark) | MIT | Speech activity detection for voice input |

---

## What's Next for Brew

**Menu-agnostic deployment.** The menu is loaded from a JSON file. Swap it out, and Brew becomes a taco shop, a pizza place, or a pharmacy pickup counter. The next step is building a pipeline that takes any restaurant's menu and automatically generates a ready-to-deploy voice ordering agent -- menu data, system prompt, and item images included.

**Multilingual support with real-time language switching.** Gemini's native audio model already understands multiple languages. The direction is automatic language detection mid-conversation -- if a customer starts in English and switches to Spanish, the agent detects the shift and responds in Spanish without any button press or setting change. In areas with high bilingual traffic, this removes a friction point that most ordering systems don't attempt to address.

The hard part was proving that a live voice agent can handle complex, modifier-heavy ordering with interruptions, corrections, and batch operations -- correctly and reliably. That's done. Now it's about making it work for anyone, in any language.

---

## Findings and Learnings

### Gemini Live API Behavior
- The Live API has a **10-minute session hard limit**. Brew implements proactive reconnection at 8 minutes with order context injection so the AI seamlessly continues the conversation without re-greeting the customer.
- Transient errors (1007, 1008, 1011) are common during long sessions. Exponential backoff with up to 8 retries handles these gracefully.
- Native audio models can hallucinate tool arguments (e.g., inventing item IDs). Sequential integer IDs (`item_1`, `item_2`) are far more reliable than UUIDs.

### Agent Tool Design
- Batch tools (`add_items`, `add_modifiers`) significantly reduce latency for multi-item orders. Without them, the model makes sequential tool calls with separate confirmations for each item.
- Tool docstrings are the primary interface for the model. Clear, specific docstrings with examples produce dramatically better tool-calling accuracy than vague descriptions.
- Idempotency guards on `add_modifier` prevent the model from accidentally adding the same modifier twice during retry loops.

### Audio Pipeline
- AudioWorklet provides consistent low-latency audio processing compared to the deprecated ScriptProcessorNode.
- A tool gate mechanism (blocking user audio during tool execution) prevents the model from hearing its own tool-call confirmations as user input, which would cause infinite loops.

### Cloud Run Considerations
- Session affinity is essential for WebSocket connections on Cloud Run. Without it, subsequent requests may hit different instances that don't have the session state.
- Firestore persistence for both ADK sessions and cart state ensures continuity across instance restarts and horizontal scaling events.

---

## License

This project is licensed under the [MIT License](LICENSE).
