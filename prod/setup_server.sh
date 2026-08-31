#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Setup VPS Script - Optimized for 1 Core CPU / 1GB RAM / 20GB Disk
# ==============================================================================

SWAP_SIZE_GB=4
SWAP_FILE="/swapfile"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { printf "${BLUE}[INFO]${NC} %s\n" "$*"; }
log_success() { printf "${GREEN}[SUCCESS]${NC} %s\n" "$*"; }
log_warn() { printf "${YELLOW}[WARN]${NC} %s\n" "$*"; }
log_error() { printf "${RED}[ERROR]${NC} %s\n" "$*"; }

# 1. Kiểm tra quyền root
if [[ $EUID -ne 0 ]]; then
   log_error "Vui lòng chạy script này với quyền root (sudo bash setup_server.sh)"
   exit 1
fi

log_info "Bắt đầu tối ưu hóa hệ thống máy chủ 1 Core / 1GB RAM / 20GB Disk..."

# 2. Kiểm tra dung lượng ổ đĩa
FREE_DISK_GB=$(df -BG / | awk 'NR==2 {print $4}' | tr -d 'G')
log_info "Dung lượng đĩa trống hiện tại: ${FREE_DISK_GB} GB"

if [ "$FREE_DISK_GB" -lt 6 ]; then
    log_warn "Dung lượng ổ đĩa còn ít hơn 6GB. Cân nhắc dọn dẹp trước khi tạo Swap 4GB."
fi

# 3. Cấu hình Swap 4GB
log_info "Kiểm tra và thiết lập 4GB Swap..."
CURRENT_SWAP_MB=$(free -m | awk '/Swap:/ {print $2}')

if [ "$CURRENT_SWAP_MB" -lt 3500 ]; then
    log_info "Đang tạo file Swap 4GB tại ${SWAP_FILE}..."
    swapoff -a 2>/dev/null || true
    rm -f "${SWAP_FILE}"
    
    if command -v fallocate >/dev/null 2>&1; then
        fallocate -l ${SWAP_SIZE_GB}G "${SWAP_FILE}" || dd if=/dev/zero of="${SWAP_FILE}" bs=1M count=$((SWAP_SIZE_GB * 1024)) status=progress
    else
        dd if=/dev/zero of="${SWAP_FILE}" bs=1M count=$((SWAP_SIZE_GB * 1024)) status=progress
    fi
    
    chmod 600 "${SWAP_FILE}"
    mkswap "${SWAP_FILE}"
    swapon "${SWAP_FILE}"

    if ! grep -q "${SWAP_FILE}" /etc/fstab; then
        echo "${SWAP_FILE} none swap sw 0 0" >> /etc/fstab
    fi
    log_success "Đã kích hoạt thành công 4GB Swap!"
else
    log_info "Dung lượng Swap hiện tại (${CURRENT_SWAP_MB} MB) đã đủ lớn. Giữ nguyên."
fi

# 4. Tối ưu Kernel Sysctl cho Swap & Mạng
log_info "Tối ưu hóa Kernel parameters (Sysctl)..."

cat << 'EOF' > /etc/sysctl.d/99-pia-socks-optimizer.conf
# Ưu tiên dùng RAM vật lý, chỉ đẩy sang Swap khi RAM còn < 20%
vm.swappiness=20
vm.vfs_cache_pressure=50

# Tối ưu kết nối mạng và SOCKS5 proxy
net.core.somaxconn=4096
net.ipv4.tcp_max_syn_backlog=4096
net.ipv4.ip_forward=1
net.ipv6.conf.all.disable_ipv6=0
net.ipv6.conf.default.disable_ipv6=0
fs.file-max=2097152
EOF

sysctl --system >/dev/null 2>&1 || sysctl -p /etc/sysctl.d/99-pia-socks-optimizer.conf >/dev/null 2>&1
log_success "Đã tối ưu hóa thông số Kernel!"

# 5. Kích hoạt TUN/TAP Device cho VPN
log_info "Kiểm tra TUN device (/dev/net/tun)..."
mkdir -p /dev/net
if [ ! -c /dev/net/tun ]; then
    mknod /dev/net/tun c 10 200
    chmod 666 /dev/net/tun
    log_success "Đã tạo /dev/net/tun node."
else
    log_info "/dev/net/tun đã sẵn sàng."
fi

# Load kernel modules nếu có
modprobe tun 2>/dev/null || true
modprobe wireguard 2>/dev/null || true

# 6. Chuẩn bị thư mục credentials và runtime
PROD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "${PROD_DIR}/credentials" "${PROD_DIR}/gateway/runtime"
chmod -R 777 "${PROD_DIR}/gateway/runtime"

# 7. Tự động tạo sẵn file .env từ .env.example nếu chưa có hoặc rỗng
ENV_FILE="${PROD_DIR}/.env"
ENV_EXAMPLE="${PROD_DIR}/.env.example"
if [ ! -s "${ENV_FILE}" ]; then
    if [ -f "${ENV_EXAMPLE}" ]; then
        cp "${ENV_EXAMPLE}" "${ENV_FILE}"
        log_success "Đã tự động tạo sẵn file .env từ .env.example"
    fi
else
    log_info "File .env đã tồn tại sẵn, giữ nguyên."
fi

# 8. Tự động tạo sẵn file tài khoản PIA mẫu nếu chưa có hoặc rỗng
PIA_ACCOUNT_FILE="${PROD_DIR}/credentials/pia_account_1"
if [ ! -s "${PIA_ACCOUNT_FILE}" ]; then
    cat << 'EOF' > "${PIA_ACCOUNT_FILE}"
p1234567_CHANGE_ME
your_password_CHANGE_ME
EOF
    chmod 600 "${PIA_ACCOUNT_FILE}"
    log_success "Đã tự động tạo sẵn file mẫu: credentials/pia_account_1"
else
    log_info "File credentials/pia_account_1 đã tồn tại sẵn, giữ nguyên."
fi

# 9. Kiểm tra Docker & Docker Compose
log_info "Kiểm tra Docker Engine..."
if ! command -v docker >/dev/null 2>&1; then
    log_warn "Chưa tìm thấy Docker! Bạn có thể cài đặt nhanh bằng lệnh:"
    echo "  curl -fsSL https://get.docker.com | sh"
else
    log_success "Docker đã được cài đặt: $(docker --version)"
fi

echo ""
echo "=========================================================================="
log_success "Hoàn tất thiết lập máy chủ!"
echo "=========================================================================="
echo "Các file cấu hình đã được tạo sẵn. Bạn chỉ cần sửa 2 file:"
echo ""
echo " 1. Nhập tài khoản PIA thật của bạn:"
echo "    nano ${PROD_DIR}/credentials/pia_account_1"
echo ""
echo " 2. (Tùy chọn) Chỉnh sửa SOCKS5 username/password trong .env:"
echo "    nano ${PROD_DIR}/.env"
echo ""
echo " 3. Khởi động toàn bộ 36 Worker:"
echo "    cd ${PROD_DIR} && docker compose pull && docker compose up -d"
echo "=========================================================================="
