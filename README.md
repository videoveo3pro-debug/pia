# PIA SOCKS5 Multi-Worker Proxy Gateway & CLI

Hệ thống Proxy SOCKS5 tập trung hiệu năng cao, điều phối **32 Worker VPN Private Internet Access (PIA)** hoạt động song song trong các container biệt lập, đảm bảo **luôn có ít nhất 20 IP công khai độc lập hoạt động đồng thời**, hỗ trợ tự động xoay IP (Auto-Rotate) mượt mà với **100% Uptime (Zero-Downtime)**.

---

## ⚡ Ứng Dụng Quản Lý CLI (`pia-proxy` / `zsocks`)

Toàn bộ hệ thống hiện đã được tích hợp bộ công cụ CLI hiện đại, trực quan giúp quản trị, vận hành, kiểm thử và mở rộng pool proxy chỉ bằng các câu lệnh đơn giản:

```bash
# Cài đặt symlink CLI vào PATH (nếu chưa có):
chmod +x bin/pia-proxy
ln -sf $(pwd)/bin/pia-proxy ~/.local/bin/pia-proxy
ln -sf $(pwd)/bin/pia-proxy ~/.local/bin/zsocks
```

### Các lệnh CLI chính:

| Lệnh | Chức năng |
| :--- | :--- |
| `pia-proxy doctor` | Kiểm tra môi trường hệ thống: Docker, TUN device, Swap, RAM, Port |
| `pia-proxy config show` | Xem thông tin cấu hình, credentials, ports |
| `pia-proxy config set-credentials` | Nhập tài khoản PIA (Username / Password) |
| `pia-proxy config set-proxy-auth` | Đổi thông tin đăng nhập SOCKS5 (`user`, `pass`) |
| `pia-proxy start` | Khởi động hệ thống thông minh (Staggered Boot chống nghẽn CPU) |
| `pia-proxy stop` | Dừng an toàn toàn bộ hệ thống hoặc từng worker cụ thể |
| `pia-proxy restart [-W worker]` | Khởi động lại cụm proxy hoặc một worker chỉ định |
| `pia-proxy status [-w]` | Xem bảng trạng thái trực tiếp: Exit IP, Uptime, Worker READY, Unique IPs |
| `pia-proxy scale <N>` | **Mở rộng / thu gọn quy mô động** (ví dụ: `scale 20`, `scale 32`) Zero-Downtime |
| `pia-proxy rotate [ID] [--all]` | Kích hoạt xoay IP ngay lập tức cho 1 worker hoặc toàn bộ pool |
| `pia-proxy test [-n 5]` | Kiểm tra kết nối SOCKS5 gateway, đo độ trễ, đếm IP và xác nhận Zero-Leak |
| `pia-proxy export [-f format]` | **Xuất proxy định dạng sẵn** cho tool nuôi nick, Gologin, AdsPower, bot |
| `pia-proxy logs [-f]` | Theo dõi log real-time của worker hoặc gateway |

---

## 🚀 Đặc Điểm Nổi Bật

- **Cổng SOCKS5 Duy Nhất Cho Mọi Ứng Dụng:**  
  `socks5h://proxy_user:proxy_password_secure123@<IP_SERVER>:1087`
- **Cân Bằng Tải Thông Minh (Round-Robin):**  
  Mỗi kết nối / request mới tự động chuyển hướng qua một Worker VPN khác nhau, mang lại dải IP đa dạng và phân bổ đều.
- **Quy Tắc Xoay Vòng IP (Strict Rotation Rules):**
  - Chu kỳ tự động xoay: **36s – 69s**.
  - Giới hạn cứng Uptime: **70s** (Bất kỳ IP nào đạt 70s sẽ bị ép rotate ngay lập tức).
  - Khống chế dung lượng: Không bao giờ để số worker khả dụng tụt dưới **20 IP**.
- **Tối Ưu Phần Cứng Tuyệt Đối (Zero CPU Overhead):**
  - Chạy mượt mà ngay cả trên VPS 1 vCPU / 1GB RAM.
  - Sử dụng lightweight TCP healthchecks trên cổng 1080, loại bỏ hoàn toàn hiện tượng 503 flapping và CPU spikes.
- **Bảo Mật Zero-Leak:**
  - Tường lửa iptables killswitch trong từng worker chặn 100% rò rỉ IP gốc của VPS.

---

## 📖 Ví Dụ Sử Dụng Nhanh

### 1. Xuất chuỗi proxy dùng cho phần mềm:
```bash
# Định dạng chuẩn IP:PORT:USER:PASS (dùng cho antidetect browser, bot, tool)
pia-proxy export --format standard
# Kết quả: 14.169.55.237:1087:proxy_user:proxy_password_secure123

# Định dạng URL:
pia-proxy export --format url
# Kết quả: socks5h://proxy_user:proxy_password_secure123@14.169.55.237:1087
```

### 2. Xem bảng trạng thái trực quan:
```bash
pia-proxy status
# Giám sát trực tiếp liên tục mỗi 2 giây:
pia-proxy status --watch -i 2
```

### 3. Mở rộng số lượng worker khi cần:
```bash
# Tăng lên 32 worker:
pia-proxy scale 32

# Giảm xuống 20 worker:
pia-proxy scale 20
```

### 4. Kiểm thử chất lượng proxy & Zero-leak:
```bash
pia-proxy test --count 5
```

---

## 🛠️ Triển Khai Thủ Công & Link Trực Tiếp

- **Web Dashboard:** `http://<IP_SERVER>:8007/`
- **API Status:** `http://<IP_SERVER>:8007/api/status`
- **HAProxy Live Stats:** `http://<IP_SERVER>:8411/`
- **Hướng dẫn cấu hình nâng cao:** [prod/README.md](prod/README.md)
