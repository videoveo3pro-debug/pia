# Hướng Dẫn Triển Khai & Vận Hành PIA SOCKS5 Proxy Pool (32 Workers)

Tài liệu này cung cấp hướng dẫn chi tiết từ A - Z để triển khai hệ thống **32 Worker PIA SOCKS5 Proxy Gateway** lên mọi máy chủ Linux (kể cả VPS cấu hình tối thiểu 1 vCPU / 1GB RAM) một cách nhanh chóng, ổn định 100% uptime và chính xác tuyệt đối.

---

## 1. Thông Số & Nguyên Lý Hoạt Động Cốt Lõi

- **Tổng số Worker:** **32** containers chạy độc lập song song (`vpn-worker-1` đến `vpn-worker-32`).
- **Cam kết số IP hoạt động đồng thời:** **Luôn luôn >= 20 IP READY** tại mọi thời điểm.
- **Cơ chế xoay vòng IP (Auto-Rotate):**
  - **Chu kỳ xoay mặc định:** **36s – 69s** (`AUTO_ROTATE_INTERVAL_MIN_SECONDS=36`, `AUTO_ROTATE_INTERVAL_MAX_SECONDS=69`).
  - **Uptime trần tối đa:** **70s** (`AUTO_ROTATE_MAX_UPTIME_SECONDS=70`). Bất kỳ IP nào đạt uptime 70s sẽ được đưa lên hàng đợi ưu tiên cao nhất (`priority = 0`) để xoay IP mới ngay lập tức.
  - **Số worker rotate cùng lúc:** Tối đa 3 - 5 workers, tự động khoá không cho xoay thêm nếu số worker sẵn sàng sắp tụt dưới ngưỡng 20.
- **HAProxy Gateway (Cổng SOCKS5 tập trung):**
  - **Endpoint:** `socks5h://proxy_user:proxy_password_secure123@<IP_SERVER>:1087`
  - **Cân bằng tải:** `balance roundrobin` (mỗi request đi qua 1 IP VPN khác nhau).
  - **Kiểm tra sức khỏe:** Lightweight TCP check trên cổng 1080 (`check port 1080 inter 5s fastinter 2s downinter 3s rise 1 fall 2`). **Không dùng HTTP check** để tránh tạo tiến trình fork làm nghẽn CPU.
- **Bảo mật & Chống rò rỉ (Zero-Leak):**
  - Mọi worker đều được cấu hình tường lửa `iptables` nghiêm ngặt (VPN Killswitch), chặn toàn bộ traffic ra ngoài qua `eth0`, chỉ cho phép đi qua interface VPN `wgpia+` / `tun+`.

---

## 2. Yêu Cầu Hệ Thống

| Thành phần | Yêu cầu tối thiểu | Khuyến nghị |
| :--- | :--- | :--- |
| **Hệ điều hành** | Ubuntu 20.04 / 22.04 / Debian 11 / Debian 12 | Ubuntu 22.04 LTS |
| **CPU** | 1 vCPU | 2 vCPU |
| **RAM** | 1 GB (+ 4GB Swap) | 2 GB (+ 4GB Swap) |
| **Dung lượng đĩa** | 15 GB SSD | 25 GB SSD |
| **Cổng mạng (Ports)** | `1087` (SOCKS5 Proxy)<br>`8007` (API & Dashboard)<br>`8411` (HAProxy Stats) | Đã mở trên firewall / security group |

---

## 3. Cách Triển Khai Nhanh Nhất (1-Click Deploy - Khuyên Dùng)

### Bước 1: Tải mã nguồn lên máy chủ
Đăng nhập SSH vào server với quyền `root` và clone repository:
```bash
git clone https://github.com/videoveo3pro-debug/pia.git /root/pia
cd /root/pia/prod
```

### Bước 2: Điền thông tin tài khoản PIA
Chỉnh sửa file chứa tài khoản PIA:
```bash
nano credentials/pia_account_1
```
> **Định dạng file:**
> - Dòng 1: PIA Username (bắt đầu bằng `p`, ví dụ: `p1234567`)
> - Dòng 2: PIA Password (mật khẩu tương ứng)
>
> *(Nhấn `Ctrl + O` -> `Enter` để lưu, `Ctrl + X` để thoát)*

### Bước 3: Chạy script triển khai tự động
```bash
sudo bash deploy.sh
```

**Script `deploy.sh` sẽ tự động thực hiện hoàn toàn các thao tác sau:**
1. Khởi tạo và kích hoạt **4GB Swap** để chống tràn RAM / OOM crash.
2. Tối ưu Kernel Sysctl (`vm.swappiness=10`, `fs.file-max=100000`, `net.core.somaxconn=4096`).
3. Cài đặt Docker Engine và Docker Compose (nếu server mới chưa cài).
4. Pull 3 Docker image chính thức từ GitHub Container Registry (`ghcr.io`).
5. **Bootstrapping Session Cache:** Khởi động riêng `vpn-worker-1` trước để đăng nhập và sinh file cache token (`credentials/pia_session_slot_1.json`), tránh tình trạng 32 containers cùng đăng nhập đồng thời gây rate-limit hoặc CPU spike.
6. **Staggered Launch:** Khởi động tuần tự các worker từ `2` đến `32` (so le 0.3s) dùng lại token session.
7. Khởi động `proxy-gateway` (HAProxy) và `backend` (FastAPI).
8. Tự động chạy script kiểm tra pool proxy và in kết quả.

---

## 4. Cách Triển Khai Thủ Công Từng Bước (Manual Step-by-Step)

Nếu muốn tự kiểm soát từng bước mà không chạy script `deploy.sh`, thực hiện tuần tự như sau:

### 1. Tối ưu hệ thống & Swap
```bash
# Tạo Swap 4GB
if [ ! -f /swapfile ]; then
    fallocate -l 4G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=4096
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi

# Tối ưu sysctl
cat << 'EOF' > /etc/sysctl.d/99-pia-proxy.conf
vm.swappiness = 10
fs.file-max = 100000
net.core.somaxconn = 4096
net.ipv4.tcp_tw_reuse = 1
net.ipv4.ip_forward = 1
EOF
sysctl --system
```

### 2. Chuẩn bị file cấu hình môi trường
```bash
cd /root/pia/prod
cp .env.example .env
mkdir -p credentials
chmod 700 credentials
```
Đảm bảo trong file `.env` có các thông số chuẩn:
```env
WORKER_COUNT=32
MIN_READY_WORKERS=20
AUTO_ROTATE_INTERVAL_MIN_SECONDS=36
AUTO_ROTATE_INTERVAL_MAX_SECONDS=69
AUTO_ROTATE_MAX_UPTIME_SECONDS=70
AUTO_ROTATE_MAX_PARALLEL=3
DOCKER_RECOVERY_ENABLED=false
```

### 3. Khởi động tuần tự (Staggered Boot)
```bash
# Bước 3.1: Chạy Worker 1 để tạo session login
docker compose up -d vpn-worker-1

# Đợi 10-15s cho Worker 1 login thành công và tạo file:
# credentials/pia_session_slot_1.json

# Bước 3.2: Chạy các worker 2 -> 32
for i in $(seq 2 32); do
    docker compose up -d "vpn-worker-${i}"
    sleep 0.3
done

# Bước 3.3: Khởi động HAProxy Gateway & Backend
docker compose up -d proxy-gateway backend
```

---

## 5. Kiểm Tra & Giám Sát Sau Triển Khai

### 1. Chạy script kiểm tra tổng thể hệ thống:
```bash
python3 check_proxy.sh
```
Script sẽ xuất bảng chi tiết:
- Danh sách 32 workers, trạng thái `READY`, địa chỉ Exit IP, thời gian `UPTIME` (báo động nếu >70s), số lần xoay IP.
- Tổng số IP độc lập đang hoạt động (yêu cầu >= 20).
- Kết quả test 5 request liên tiếp qua SOCKS5 Gateway.
- Tải CPU và RAM hiện tại.

### 2. Kiểm tra nhanh kết nối SOCKS5 từ bên ngoài:
```bash
curl -x socks5h://proxy_user:proxy_password_secure123@<IP_SERVER>:1087 https://api.ipify.org
```

### 3. Kiểm tra trạng thái API Backend:
```bash
curl http://127.0.0.1:8007/api/status
```

### 4. Truy cập Web Dashboard:
- **Web Quản lý Proxy & Worker:** `http://<IP_SERVER>:8007/`
- **HAProxy Live Stats Dashboard:** `http://<IP_SERVER>:8411/`

---

## 6. Quy Trình Cập Nhật Mã Nguồn & Tái Triển Khai (Update)

Khi có bản cập nhật source code mới trên GitHub:

1. **GitHub Actions CI/CD:** Khi push commit lên nhánh `main`, GitHub Actions tự động build và push các image mới (`pia-backend:latest` và `pia-worker:latest`) lên GHCR.
2. **Cập nhật trên Server:**
```bash
cd /root/pia/prod

# 1. Kéo code mới về
git pull origin main

# 2. Tải image mới nhất từ GHCR
docker compose pull backend

# 3. Tái khởi động dịch vụ mà không ngắt quãng các worker VPN
docker compose up -d --no-deps backend proxy-gateway
```

---

## 7. Xử Lý Sự Cố Thường Gặp (Troubleshooting)

### Sự cố 1: Proxy bị lỗi 503 hoặc rớt kết nối
- **Nguyên nhân:** HAProxy health check đang kiểm tra sai cổng hoặc kiểm tra qua HTTP 9000 làm nghẽn worker.
- **Khắc phục:** Đảm bảo cấu hình trong `docker-compose.yml` sử dụng:
  ```haproxy
  server workerX vpn-worker-X:1080 check port 1080 inter 5s fastinter 2s downinter 3s rise 1 fall 2
  ```

### Sự cố 2: CPU Load tăng cao (> 50)
- **Nguyên nhân:** Các container bị watchdog kích hoạt khởi động lại đồng loạt hoặc swap thrashing.
- **Khắc phục:**
  - Kiểm tra biến `DOCKER_RECOVERY_ENABLED=false` trong file `.env`.
  - Đảm bảo đã kích hoạt Swap 4GB (`free -h`).
  - Kiểm tra số lượng worker xoay đồng thời không vượt quá 3-5: `AUTO_ROTATE_MAX_PARALLEL=3`.

### Sự cố 3: Worker báo "unauthorized" hoặc không nhận IP
- **Nguyên nhân:** File tài khoản `credentials/pia_account_1` chứa sai username/password, hoặc file session token cũ bị hỏng.
- **Khắc phục:**
  ```bash
  rm -f credentials/pia_session_slot_*.json
  docker compose restart vpn-worker-1
  # Đợi 15s để sinh lại session token mới rồi restart các worker còn lại
  ```
