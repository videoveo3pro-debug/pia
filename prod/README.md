# Gói Triển Khai Production (1 Core CPU / 1GB RAM / 20GB Disk)

Thư mục này chứa toàn bộ cấu hình, script tối ưu hóa và `docker-compose.yml` để chạy **28 Worker PIA SOCKS5 Proxy** ổn định trên máy chủ cấu hình tối thiểu (1 vCPU, 1GB RAM, 20GB Disk) với các đặc điểm:
- **Cung cấp >20 IP VPN độc lập cùng lúc:** Mỗi worker được chỉ định một vùng địa lý riêng biệt trên 4 châu lục (Mỹ, Châu Âu, Châu Á, Úc, Mỹ Latin).
- **Tự động xoay IP (Auto-Rotate):** Mỗi worker tự động đổi IP định kỳ 60s - 110s, **tuyệt đối không IP nào tồn tại quá 150 giây**.
- **CPU ổn định ~75% - 80%:** Khởi động so le (staggered boot), chống restart loop và swap thrashing.
- **Zero-Leak Protection:** Kiểm tra sức khỏe HAProxy nghiêm ngặt trên cổng 9000 kết hợp iptables killswitch trong từng container, loại bỏ 100% rủi ro lộ IP gốc máy chủ.

---

## 1. Cơ Chế Triển Khai Nhanh (1-Click Master Deploy)

Hệ thống có sẵn script **`deploy.sh`** tự động hóa toàn bộ quy trình:
1. Tự động tạo **4GB Swap** và tối ưu Kernel Sysctl (`vm.swappiness=20`, `somaxconn=4096`).
2. Tự động cài đặt Docker Engine và Docker Compose plugin (nếu VPS mới tinh chưa có).
3. Kiểm tra file tài khoản PIA (`credentials/pia_account_1`).
4. **Bootstrapping Session Cache:** Khởi động Worker 1 trước để đăng nhập và tạo `pia_session_slot_1.json`.
5. **Staggered Launch:** Lần lượt khởi động 27 worker còn lại (so le 0.3s) nạp sẵn token cache mà không gây nghẽn CPU.
6. Khởi động HAProxy Gateway và Backend API.
7. Tự động chạy bài kiểm tra và xuất báo cáo IP.

---

## 2. Hướng Dẫn Triển Khai Trên VPS

### Bước 1: Sao chép thư mục `prod` lên server
```bash
git clone https://github.com/videoveo3pro-debug/pia.git
cd pia/prod
```
*(Hoặc copy toàn bộ thư mục `prod` lên server qua scp / rsync).*

### Bước 2: Điền tài khoản PIA
```bash
nano credentials/pia_account_1
```
*(Dòng 1: Username dạng pXXXXXXX, Dòng 2: Password).*

### Bước 3: Chạy script triển khai tự động (1 lệnh duy nhất)
```bash
sudo bash deploy.sh
```
*Script sẽ tự động làm toàn bộ các bước và in kết quả kiểm tra pool proxy.*

---

## 3. Kiểm Tra & Vận Hành

### Kiểm tra nhanh trạng thái pool proxy bất kỳ lúc nào:
```bash
bash check_proxy.sh
```
*Script sẽ in chi tiết:*
- Trạng thái từng Worker và IP VPN tương ứng.
- Tổng số IP độc lập đang hoạt động (đảm bảo >20 IP).
- Kết quả test 5 request qua SOCKS5 gateway (kiểm tra Zero-Leak).
- Tải CPU và RAM hiện tại.

### Kiểm tra thủ công:
1. **Kiểm tra IP xuất ra qua Gateway SOCKS5:**
   ```bash
   curl -x socks5h://proxy_user:proxy_password_secure123@127.0.0.1:1087 https://api.ipify.org
   ```
2. **Kiểm tra API trạng thái Backend:**
   ```bash
   curl http://127.0.0.1:8007/api/status
   ```
3. **Xem Dashboard HAProxy Stats:**
   Truy cập `http://<IP_VPS>:8411/`
