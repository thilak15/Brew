#!/usr/bin/env bash
# ============================================================================
# Brew — Automated GCP Cloud Run Deployment Script
# ============================================================================
# Usage:
#   ./deploy.sh                     # Interactive — prompts for project ID & API key
#   ./deploy.sh --project MY_ID --api-key MY_KEY --region us-central1
#
# What it does:
#   1. Checks/installs gcloud CLI
#   2. Authenticates with GCP
#   3. Enables required APIs
#   4. Creates Artifact Registry (if needed)
#   5. Builds & pushes backend Docker image
#   6. Deploys backend to Cloud Run
#   7. Builds & pushes frontend Docker image (with backend URL baked in)
#   8. Deploys frontend to Cloud Run
#   9. Prints the live URLs
# ============================================================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

log()   { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
err()   { echo -e "${RED}[✗]${NC} $*" >&2; }
step()  { echo -e "\n${CYAN}${BOLD}━━━ $* ━━━${NC}"; }

# ─── Parse Arguments ───────────────────────────────────────────────────────
PROJECT_ID=""
API_KEY=""
REGION="us-central1"
REPO_NAME="brew-repo"

while [[ $# -gt 0 ]]; do
  case $1 in
    --project)   PROJECT_ID="$2"; shift 2 ;;
    --api-key)   API_KEY="$2"; shift 2 ;;
    --region)    REGION="$2"; shift 2 ;;
    *)           err "Unknown arg: $1"; exit 1 ;;
  esac
done

# ─── Get script directory (project root) ───────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${BOLD}"
echo "  ☕  Brew — GCP Cloud Run Deployment"
echo -e "${NC}"

# ─── Step 1: Check Prerequisites ──────────────────────────────────────────
step "Step 1/8 — Checking prerequisites"

# Docker
if ! command -v docker &>/dev/null; then
  err "Docker is not installed. Install it from https://docs.docker.com/get-docker/"
  exit 1
fi
log "Docker found: $(docker --version | head -1)"

# gcloud
if ! command -v gcloud &>/dev/null; then
  warn "gcloud CLI not found. Installing..."
  if [[ "$(uname)" == "Darwin" ]]; then
    if command -v brew &>/dev/null; then
      brew install --cask google-cloud-sdk
    else
      curl https://sdk.cloud.google.com | bash -s -- --disable-prompts
      export PATH="$HOME/google-cloud-sdk/bin:$PATH"
    fi
  else
    curl https://sdk.cloud.google.com | bash -s -- --disable-prompts
    export PATH="$HOME/google-cloud-sdk/bin:$PATH"
  fi

  if ! command -v gcloud &>/dev/null; then
    err "gcloud install failed. Install manually: https://cloud.google.com/sdk/docs/install"
    exit 1
  fi
  log "gcloud installed successfully"
else
  log "gcloud found: $(gcloud --version 2>/dev/null | head -1)"
fi

# ─── Step 2: Authenticate ─────────────────────────────────────────────────
step "Step 2/8 — Authenticating with GCP"

# Check if already authenticated
CURRENT_ACCOUNT=$(gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null || true)
if [[ -z "$CURRENT_ACCOUNT" ]]; then
  warn "Not logged in. Opening browser for authentication..."
  gcloud auth login
else
  log "Already authenticated as: $CURRENT_ACCOUNT"
fi

# ─── Get Project ID ───────────────────────────────────────────────────────
if [[ -z "$PROJECT_ID" ]]; then
  CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null || true)
  if [[ -n "$CURRENT_PROJECT" && "$CURRENT_PROJECT" != "(unset)" ]]; then
    echo -e "  Current project: ${BOLD}$CURRENT_PROJECT${NC}"
    read -rp "  Use this project? (Y/n): " USE_CURRENT
    if [[ "${USE_CURRENT,,}" != "n" ]]; then
      PROJECT_ID="$CURRENT_PROJECT"
    fi
  fi
  if [[ -z "$PROJECT_ID" ]]; then
    read -rp "  Enter your GCP Project ID: " PROJECT_ID
  fi
fi

gcloud config set project "$PROJECT_ID"
log "Using project: $PROJECT_ID"

# ─── Get API Key ──────────────────────────────────────────────────────────
if [[ -z "$API_KEY" ]]; then
  # Try to read from backend/.env
  if [[ -f backend/.env ]]; then
    EXISTING_KEY=$(grep -oP 'GOOGLE_API_KEY=\K.*' backend/.env 2>/dev/null || true)
    if [[ -n "$EXISTING_KEY" && "$EXISTING_KEY" != "your_api_key_here" ]]; then
      log "Found API key in backend/.env"
      API_KEY="$EXISTING_KEY"
    fi
  fi
  if [[ -z "$API_KEY" ]]; then
    read -rp "  Enter your GOOGLE_API_KEY (from https://aistudio.google.com/apikey): " API_KEY
  fi
fi

# ─── Step 3: Enable APIs ──────────────────────────────────────────────────
step "Step 3/8 — Enabling required APIs"

gcloud services enable run.googleapis.com artifactregistry.googleapis.com --quiet
log "Cloud Run and Artifact Registry APIs enabled"

# ─── Step 4: Create Artifact Registry ──────────────────────────────────────
step "Step 4/8 — Setting up Artifact Registry"

REGISTRY="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME"

if gcloud artifacts repositories describe "$REPO_NAME" --location="$REGION" &>/dev/null; then
  log "Repository '$REPO_NAME' already exists"
else
  gcloud artifacts repositories create "$REPO_NAME" \
    --repository-format=docker \
    --location="$REGION" \
    --quiet
  log "Created repository: $REPO_NAME"
fi

gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet
log "Docker authenticated with Artifact Registry"

# ─── Step 5: Build & Push Backend ──────────────────────────────────────────
step "Step 5/8 — Building & pushing backend image"

BACKEND_IMAGE="$REGISTRY/brew-backend:latest"
docker build -t "$BACKEND_IMAGE" ./backend
log "Backend image built"

docker push "$BACKEND_IMAGE"
log "Backend image pushed to $BACKEND_IMAGE"

# ─── Step 6: Deploy Backend to Cloud Run ───────────────────────────────────
step "Step 6/8 — Deploying backend to Cloud Run"

gcloud run deploy brew-backend \
  --image "$BACKEND_IMAGE" \
  --region "$REGION" \
  --port 8000 \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_API_KEY=$API_KEY,GOOGLE_GENAI_USE_VERTEXAI=FALSE,BREW_AGENT_MODEL=gemini-2.5-flash-native-audio-preview-12-2025" \
  --memory 512Mi \
  --timeout 300 \
  --session-affinity \
  --quiet

BACKEND_URL=$(gcloud run services describe brew-backend --region "$REGION" --format="value(status.url)")
log "Backend deployed: $BACKEND_URL"

# Derive the wss:// URL (strip https:// and prepend wss://)
BACKEND_WSS="wss://${BACKEND_URL#https://}"
log "WebSocket URL: $BACKEND_WSS"

# ─── Step 7: Build & Push Frontend ─────────────────────────────────────────
step "Step 7/8 — Building & pushing frontend image (with backend URL)"

FRONTEND_IMAGE="$REGISTRY/brew-frontend:latest"
docker build \
  --build-arg "NEXT_PUBLIC_WS_URL=$BACKEND_WSS" \
  -t "$FRONTEND_IMAGE" \
  ./frontend
log "Frontend image built (WS_URL=$BACKEND_WSS)"

docker push "$FRONTEND_IMAGE"
log "Frontend image pushed to $FRONTEND_IMAGE"

# ─── Step 8: Deploy Frontend to Cloud Run ──────────────────────────────────
step "Step 8/8 — Deploying frontend to Cloud Run"

gcloud run deploy brew-frontend \
  --image "$FRONTEND_IMAGE" \
  --region "$REGION" \
  --port 3000 \
  --allow-unauthenticated \
  --memory 256Mi \
  --quiet

FRONTEND_URL=$(gcloud run services describe brew-frontend --region "$REGION" --format="value(status.url)")

# ─── Done! ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}  ☕ Brew is LIVE on Google Cloud Run!${NC}"
echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  ${BOLD}Frontend:${NC}  $FRONTEND_URL"
echo -e "  ${BOLD}Backend:${NC}   $BACKEND_URL"
echo -e "  ${BOLD}WebSocket:${NC} $BACKEND_WSS"
echo ""
echo -e "  Open ${CYAN}$FRONTEND_URL${NC} in Chrome and start ordering! 🎤"
echo ""
echo -e "  ${YELLOW}To tear down:${NC}"
echo "    gcloud run services delete brew-frontend --region $REGION --quiet"
echo "    gcloud run services delete brew-backend --region $REGION --quiet"
echo ""
