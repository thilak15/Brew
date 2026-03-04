#!/usr/bin/env bash
# ============================================================================
# Brew — One-Time GCP Setup for GitHub Actions CI/CD
# ============================================================================
# Run this ONCE to configure:
#   1. Enable required APIs
#   2. Create Artifact Registry
#   3. Create a Service Account for GitHub Actions
#   4. Set up Workload Identity Federation (keyless auth)
#   5. Print the GitHub Secrets you need to add
#
# Usage:
#   ./setup-gcp.sh --project YOUR_PROJECT_ID --repo owner/repo-name
# ============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[✗]${NC} $*" >&2; }
step() { echo -e "\n${CYAN}${BOLD}━━━ $* ━━━${NC}"; }

# ─── Parse Arguments ──────────────────────────────────────────────────────
PROJECT_ID=""
GITHUB_REPO=""
REGION="us-central1"
SA_NAME="github-actions-deployer"
POOL_NAME="github-actions-pool"
PROVIDER_NAME="github-provider"
REPO_NAME="brew-repo"

while [[ $# -gt 0 ]]; do
  case $1 in
    --project) PROJECT_ID="$2"; shift 2 ;;
    --repo)    GITHUB_REPO="$2"; shift 2 ;;
    --region)  REGION="$2"; shift 2 ;;
    *)         err "Unknown arg: $1"; exit 1 ;;
  esac
done

if [[ -z "$PROJECT_ID" ]]; then
  read -rp "Enter your GCP Project ID: " PROJECT_ID
fi
if [[ -z "$GITHUB_REPO" ]]; then
  read -rp "Enter your GitHub repo (e.g. thilak15/Brew): " GITHUB_REPO
fi

echo -e "\n${BOLD}☕ Brew — GCP CI/CD Setup${NC}\n"
echo "  Project:  $PROJECT_ID"
echo "  GitHub:   $GITHUB_REPO"
echo "  Region:   $REGION"
echo ""

gcloud config set project "$PROJECT_ID" --quiet

# ─── Step 1: Enable APIs ─────────────────────────────────────────────────
step "Step 1/5 — Enabling APIs"

gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  iamcredentials.googleapis.com \
  iam.googleapis.com \
  --quiet
log "APIs enabled"

# ─── Step 2: Create Artifact Registry ─────────────────────────────────────
step "Step 2/5 — Creating Artifact Registry"

if gcloud artifacts repositories describe "$REPO_NAME" --location="$REGION" &>/dev/null; then
  log "Repository '$REPO_NAME' already exists"
else
  gcloud artifacts repositories create "$REPO_NAME" \
    --repository-format=docker \
    --location="$REGION" \
    --quiet
  log "Created repository: $REPO_NAME"
fi

# ─── Step 3: Create Service Account ──────────────────────────────────────
step "Step 3/5 — Creating Service Account"

SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

if gcloud iam service-accounts describe "$SA_EMAIL" &>/dev/null; then
  log "Service account '$SA_NAME' already exists"
else
  gcloud iam service-accounts create "$SA_NAME" \
    --display-name="GitHub Actions Deployer" \
    --quiet
  log "Created service account: $SA_EMAIL"
  warn "Waiting 10s for IAM propagation..."
  sleep 10
fi

# Grant roles
for ROLE in "roles/run.admin" "roles/artifactregistry.writer" "roles/iam.serviceAccountUser"; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="$ROLE" \
    --quiet >/dev/null
done
log "Granted roles: Cloud Run Admin, Artifact Registry Writer, Service Account User"

# ─── Step 4: Workload Identity Federation ─────────────────────────────────
step "Step 4/5 — Setting up Workload Identity Federation"

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")

# Create pool
if gcloud iam workload-identity-pools describe "$POOL_NAME" --location=global &>/dev/null; then
  log "Workload Identity Pool '$POOL_NAME' already exists"
else
  gcloud iam workload-identity-pools create "$POOL_NAME" \
    --location=global \
    --display-name="GitHub Actions Pool" \
    --quiet
  log "Created Workload Identity Pool"
fi

# Create provider
PROVIDER_EXISTS=$(gcloud iam workload-identity-pools providers list \
  --workload-identity-pool="$POOL_NAME" \
  --location=global \
  --format="value(name)" 2>/dev/null | grep "$PROVIDER_NAME" || true)

if [[ -n "$PROVIDER_EXISTS" ]]; then
  log "Provider '$PROVIDER_NAME' already exists"
else
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_NAME" \
    --workload-identity-pool="$POOL_NAME" \
    --location=global \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
    --attribute-condition="assertion.repository == '${GITHUB_REPO}'" \
    --quiet
  log "Created OIDC provider for GitHub Actions"
fi

# Allow the pool to impersonate the service account
gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_NAME}/attribute.repository/${GITHUB_REPO}" \
  --quiet >/dev/null
log "Linked pool to service account"

# ─── Step 5: Output GitHub Secrets ────────────────────────────────────────
step "Step 5/5 — GitHub Secrets to Add"

WIF_PROVIDER="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_NAME}/providers/${PROVIDER_NAME}"

echo ""
echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}  ✅ GCP setup complete!${NC}"
echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  Now go to: ${CYAN}https://github.com/${GITHUB_REPO}/settings/secrets/actions${NC}"
echo ""
echo -e "  Add these ${BOLD}4 repository secrets:${NC}"
echo ""
echo -e "  ${BOLD}GCP_PROJECT_ID${NC}"
echo -e "  ${PROJECT_ID}"
echo ""
echo -e "  ${BOLD}WIF_PROVIDER${NC}"
echo -e "  ${WIF_PROVIDER}"
echo ""
echo -e "  ${BOLD}WIF_SERVICE_ACCOUNT${NC}"
echo -e "  ${SA_EMAIL}"
echo ""
echo -e "  ${BOLD}GOOGLE_API_KEY${NC}"
echo -e "  (your Google AI Studio API key)"
echo ""
echo -e "  Once added, every push to ${BOLD}main${NC} will auto-deploy to Cloud Run! 🚀"
echo ""
