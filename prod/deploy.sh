#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# One-Click Master Deployment Script for PIA SOCKS5 Multi-Worker Proxy Pool
# Toi uu hoa: 1 Core CPU / 1GB RAM / 20GB Disk
# Mục tiêu: >20 IP VPN doc lap, Tu dong xoay IP (khong qua 150s), CPU ~80%
# ==============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { printf "${BLUE}[INFO]${NC} %s\n" "$*"; }
log_success() { printf "${GREEN}[SUCCESS]${NC} %s\n" "$*"; }
log_warn() { printf "${YELLOW}[WARN]${NC} %s\n" "$*"; }
log_error() { printf "${RED}[ERROR]${NC} %s\n" "$*"; }

PROD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${PROD_DIR}"

echo "=========================================================================="
echo "  Private Internet Access (PIA) SOCKS5 Proxy Pool - Master Deploy Script"
echo "  Ho tro: >20 IP doc lap | Auto-Rotate <= 150s | Zero-Leak | 1 vCPU / 1GB RAM"
echo "=========================================================================="

# 1. Kiem tra quyen root
if [[ $EUID -ne 0 ]]; then
   log_error "Vui long chay script voi quyen root (sudo bash deploy.sh)"
   exit 1
fi

# 2. Chay setup toi uu he thong (Swap 4GB, sysctl, tun device)
log_info "[1/6] Thiet lap & toi uu hoa he thong may chu..."
bash "${PROD_DIR}/setup_server.sh"

# 3. Kiem tra & cai dat Docker neu chua co
log_info "[2/6] Kiem tra Docker & Docker Compose..."
if ! command -v docker >/dev/null 2>&1; then
    log_info "Docker chua duoc cai dat. Dang tu dong cai dat Docker Engine..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker.service
    log_success "Da cai dat xong Docker Engine!"
fi

# 4. Kiem tra tai khoan PIA
log_info "[3/6] Kiem tra tai khoan Private Internet Access..."
PIA_FILE="${PROD_DIR}/credentials/pia_account_1"
if [ ! -s "${PIA_FILE}" ] || grep -q 'CHANGE_ME' "${PIA_FILE}"; then
    log_warn "Chua co thong tin tai khoan PIA tai: ${PIA_FILE}"
    echo "Vui long nhap tai khoan PIA cua ban:"
    read -p "PIA Username (vd: p1234567): " pia_u
    read -sp "PIA Password: " pia_p
    echo ""
    if [ -n "${pia_u}" ] && [ -n "${pia_p}" ]; then
        printf "%s\n%s\n" "${pia_u}" "${pia_p}" > "${PIA_FILE}"
        chmod 600 "${PIA_FILE}"
        log_success "Da luu tai khoan vao ${PIA_FILE}"
    else
        log_error "Tai khoan khong duoc de trong! Vui long sua file ${PIA_FILE} va chay lai."
        exit 1
    fi
else
    log_success "Tai khoan PIA da san sang tai ${PIA_FILE}"
fi

# Doc so luong worker tu .env
ENV_FILE="${PROD_DIR}/.env"
WORKER_COUNT=$(grep -E '^WORKER_COUNT=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d ' ' || echo "38")
WORKER_COUNT="${WORKER_COUNT:-38}"
BACKEND_IMG=$(grep -E '^BACKEND_IMAGE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d ' ' || echo "ghcr.io/videoveo3pro-debug/pia-backend:latest")
WORKER_IMG=$(grep -E '^WORKER_IMAGE=' "${ENV_FILE}" | cut -d'=' -f2 | tr -d ' ' || echo "ghcr.io/videoveo3pro-debug/pia-worker:latest")

# 5. Tai 3 Docker image chinh (nhanh va khong gay nghen nhu docker compose pull)
log_info "[4/6] Kiem tra va cap nhat 3 Docker image chinh..."
docker pull "${WORKER_IMG}" || true
docker pull "${BACKEND_IMG}" || true
docker pull "haproxy:2.9-alpine" || true
log_success "Cac Docker image da san sang!"

# 6. Khoi dong thong minh (Staggered Boot) de chong CPU spike va OOM
log_info "[5/6] Khoi dong cum proxy (${WORKER_COUNT} Workers)..."

# Buoc 6.1: Khoi dong Worker 1 truoc de dang nhap va tao Session Token Cache
log_info "  -> Khoi dong Worker 1 de tao Session Cache..."
docker compose up -d vpn-worker-1

log_info "  -> Dang cho Worker 1 dang nhap va luu phien (Session Token)..."
SESSION_FILE="${PROD_DIR}/credentials/pia_session_slot_1.json"
WAIT_SEC=0
while [ ! -s "${SESSION_FILE}" ] && [ "${WAIT_SEC}" -lt 30 ]; do
    sleep 2
    WAIT_SEC=$((WAIT_SEC + 2))
done

if [ -s "${SESSION_FILE}" ]; then
    log_success "Da tao thanh cong Session Token Cache (${SESSION_FILE})!"
else
    log_warn "Worker 1 can them thoi gian dang nhap. Tiep tuc khoi dong cac worker khac..."
fi

# Buoc 6.2: Khoi dong tuan tu cac Worker 2 -> N (so le 0.3s chong nghen CPU 1 core)
log_info "  -> Khoi dong tuan tu cac Worker 2 den ${WORKER_COUNT}..."
for i in $(seq 2 "${WORKER_COUNT}"); do
    docker compose up -d "vpn-worker-${i}" >/dev/null 2>&1
    sleep 0.3
done
log_success "Da khoi dong xong toan bo ${WORKER_COUNT} Worker!"

# Buoc 6.3: Khoi dong Gateway & Backend API
log_info "  -> Khoi dong HAProxy Gateway & Backend API..."
docker compose up -d proxy-gateway backend
log_success "Da khoi dong HAProxy Gateway va Backend API!"

# 7. Kiem tra he thong
echo ""
log_info "[6/6] Kiem tra ket noi va tinh hop le cua Pool Proxy..."
sleep 8
python3 "${PROD_DIR}/check_proxy.sh"

echo ""
echo "=========================================================================="
log_success "TRIEN KHAI THANH CONG!"
echo "=========================================================================="
echo "- SOCKS5 Gateway:  socks5h://proxy_user:proxy_password_secure123@<IP_SERVER>:1087"
echo "- Backend Health:  http://<IP_SERVER>:8007/healthz"
echo "- HAProxy Stats:   http://<IP_SERVER>:8411/"
echo "- Lenh kiem tra:   bash ${PROD_DIR}/check_proxy.sh"
echo "=========================================================================="
