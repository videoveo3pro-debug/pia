# Gói Triển Khai Production (1 Core CPU / 1GB RAM / 20GB Disk)

Thư mục này chứa toàn bộ cấu hình, script tối ưu hóa và `docker-compose.yml` để chạy **30 Worker PIA SOCKS5 Proxy** ổn định trên máy chủ cấu hình tối thiểu (1 vCPU, 1GB RAM, 20GB Disk) với cơ chế **Zero-Leak Protection (tuyệt đối không rò rỉ IP máy chủ)**.

---

## 1. Cơ Chế Tối Ưu Hóa Sẵn Có

- **Zero-Leak VPN Protection:** Kiểm tra sức khỏe HAProxy nghiêm ngặt trên cổng 9000 (`/healthz` trả về 200 khi VPN Connected) kết hợp iptables killswitch trong từng container, loại bỏ 100% rủi ro lộ IP gốc máy chủ.
- **Hàng đợi Delay Queue (tối đa 20s):** Nếu các Worker đang xoay IP, HAProxy sẽ giữ request trong hàng đợi chờ tối đa 20s cho đến khi đường truyền VPN sẵn sàng.
- **4GB Swap tự động:** Tận dụng 20GB Disk để nâng bộ nhớ ảo lên **5GB**, loại bỏ hoàn toàn nguy cơ tràn RAM (OOM Killer).
- **Điều phối 1 CPU Core:**
  - Giới hạn `mem_limit` mỗi worker chỉ `120MB`.
  - Khởi động so le (Staggered boot) chống quá tải lúc mở 30 đường hầm VPN.
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
Bạn có thể clone git repo hoặc copy thư mục `prod` lên server:
```bash
git clone https://github.com/videoveo3pro-debug/pia.git
cd pia/prod
```

### Bước 2: Chạy script cài đặt & tối ưu VPS
```bash
sudo bash setup_server.sh
```
*Script sẽ tự động:*
- Tạo 4GB Swap và tối ưu Kernel Sysctl cho 1 Core CPU.
- Tự động tạo sẵn file `credentials/pia_account_1` và file `.env` chuẩn.

### Bước 3: Mở file và điền tài khoản PIA
```bash
nano credentials/pia_account_1
```
*(Điền Username ở dòng 1, Password ở dòng 2).*

### Bước 4: (Tùy chọn) Chỉnh sửa SOCKS5 username/password trong `.env`
```bash
nano .env
```

### Bước 5: Khởi động toàn bộ 14 Worker
```bash
docker compose pull
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
