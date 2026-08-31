# Gói Triển Khai Production (1 Core CPU / 1GB RAM / 20GB Disk)

Thư mục này chứa toàn bộ cấu hình, script tối ưu hóa và `docker-compose.yml` để chạy **tối đa 14 Worker PIA SOCKS5 Proxy** ổn định trên máy chủ cấu hình tối thiểu (1 vCPU, 1GB RAM, 20GB Disk).

---

## 1. Cơ Chế Tối Ưu Hóa Sẵn Có

- **4GB Swap tự động:** Tận dụng 20GB Disk để nâng bộ nhớ ảo lên **5GB**, loại bỏ hoàn toàn nguy cơ tràn RAM (OOM Killer).
- **Điều phối 1 CPU Core:**
  - Giới hạn `mem_limit` mỗi worker chỉ `120MB`.
  - Giãn tần suất Healthcheck / Watchdog lên `30s` - `45s` để không làm spike 100% CPU.
  - Khởi động so le (Staggered boot) chống quá tải lúc mở 14 đường hầm VPN.
- **Log Rotation:** Giới hạn mỗi container tối đa 2MB log để không làm đầy ổ đĩa.

---

## 2. Quy Trình GitHub Actions CI/CD (Tự Động Build Image)

Hệ thống đã có sẵn workflow [.github/workflows/docker-ci.yml](../.github/workflows/docker-ci.yml):

### Bước 1: Đẩy mã nguồn lên GitHub
```bash
git init
git add .
git commit -m "feat: setup CI/CD and prod deployment"
git remote add origin https://github.com/videoveo3pro-debug/pia.git
git branch -M main
git push -u origin main
```

### Bước 2: GitHub Actions tự động build & push
- Khi bạn push vào nhánh `main` hoặc tạo tag `v*`, GitHub Actions sẽ tự động build 2 image:
  - `ghcr.io/videoveo3pro-debug/pia-backend:latest`
  - `ghcr.io/videoveo3pro-debug/pia-worker:latest`
- Bạn có thể vào tab **Actions** trên GitHub để theo dõi tiến trình build.
- *(Lưu ý: Vào mục GitHub Package Settings để chuyển quyền của Image sang **Public** hoặc login docker trên VPS với GitHub PAT token).*

---

## 3. Hướng Dẫn Triển Khai Trên VPS (Server 1C/1G/20G)

### Bước 1: Sao chép thư mục `prod` lên server
Bạn có thể clone git repo hoặc copy riêng thư mục `prod` lên server:
```bash
cd /opt/pia-proxy/prod
```

### Bước 2: Chạy script tối ưu VPS (Tạo Swap & Kernel Sysctl)
```bash
sudo bash setup_server.sh
```
*Script sẽ tự động tạo 4GB Swap, cấu hình kernel sysctl, kiểm tra TUN device và chuẩn bị phân quyền.*

### Bước 3: Cấu hình tài khoản PIA
Tạo file `credentials/pia_account_1`:
```bash
cat << 'EOF' > credentials/pia_account_1
p1234567
your_password_here
EOF
chmod 600 credentials/pia_account_1
```

### Bước 4: Cập nhật biến môi trường `.env`
Mở file `.env` và thay đổi:
- `BACKEND_IMAGE`: Tên image GitHub của bạn (ví dụ `ghcr.io/username/pia-backend:latest`)
- `WORKER_IMAGE`: Tên image Worker của bạn (ví dụ `ghcr.io/username/pia-worker:latest`)
- `SOCKS5_USERNAME` & `SOCKS5_PASSWORD`: Thông tin đăng nhập Proxy SOCKS5.

### Bước 5: Khởi động hệ thống
```bash
docker compose up -d
```
> [!NOTE]
> Do chạy trên **1 Core CPU**, hệ thống sẽ mất khoảng **60 – 90 giây** để lần lượt kết nối 14 đường hầm VPN.

---

## 4. Kiểm Tra & Sử Dụng

1. **Kiểm tra trạng thái các Worker:**
   ```bash
   curl http://127.0.0.1:8007/api/status
   ```
2. **Kiểm tra IP xuất ra qua Gateway:**
   ```bash
   curl -x socks5h://proxy_user:proxy_password_secure123@127.0.0.1:1087 https://api.ipify.org
   ```
3. **Xoay IP (Rotate) một Worker bất kỳ mượt mà:**
   ```bash
   curl -X POST http://127.0.0.1:8007/api/rotate-any
   ```
4. **Xem Dashboard HAProxy Stats:**
   Truy cập `http://<IP_VPS>:8411/`
