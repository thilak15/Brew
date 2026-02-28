# Brew

Brew is a real-time, AI-powered voice ordering system for drive-thrus. It features a multimodal AI agent (using Google ADK and Gemini Live) connected to a dynamic Next.js frontend that displays a smart menu and live receipt.

## Features

- **Voice Ordering**: Talk to the Gemini Live AI to place your order.
- **Smart Menu**: Dynamic Next.js menu that updates based on the context.
- **Live Receipt**: Real-time order updates using WebSockets.

## Tech Stack

- **Backend**: Python 3.11+, FastAPI, Google ADK, Gemini Live API (Google AI Studio)
- **Frontend**: Next.js 14, TypeScript, Tailwind CSS

## Setup

### Using Docker Compose (Recommended)

1. Make sure you have Docker and Docker Compose installed.
2. In the `backend/` directory, create a `.env` file from the example and add your `GOOGLE_API_KEY`:
   ```bash
   cp backend/.env.example backend/.env
   # Add your key inside backend/.env
   ```
3. Run the complete application stack:
   ```bash
   docker-compose up -d --build
   ```

Both the Next.js frontend (http://localhost:3000) and the FastAPI backend (http://localhost:8000) will start automatically.

<details>
<summary>Manual Local Setup</summary>

### 1. Start the Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Add your GOOGLE_API_KEY to backend/.env
uvicorn main:app --reload --reload-exclude '.venv/*' --host 0.0.0.0 --port 8000
```

### 2. Start the Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

</details>

### Usage

1. Open [http://localhost:3000](http://localhost:3000) in your browser.
2. Click **Connect**, then **Start mic**.
3. Speak your order naturally to the AI!

## Project Structure

- `backend/`: FastAPI server handling WebSockets and the Gemini AI agent.
- `frontend/`: Next.js web application for the UI.
- `scripts/`: Utility scripts (e.g., generating menu images).
