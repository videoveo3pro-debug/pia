# PIA SOCKS5 Multi-Worker Proxy Gateway

Hệ thống Proxy SOCKS5 tập trung hiệu năng cao, điều phối **32 Worker VPN Private Internet Access (PIA)** hoạt động song song trong các container biệt lập, đảm bảo **luôn có ít nhất 20 IP công khai độc lập hoạt động đồng thời**, hỗ trợ tự động xoay IP (Auto-Rotate) mượt mà với **100% Uptime (Zero-Downtime)**.

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

## 📖 Hướng Dẫn Triển Khai Chi Tiết

👉 **Xem hướng dẫn chi tiết dành cho Production tại:** [prod/README.md](prod/README.md)

### Triển khai nhanh 1-Click (Khuyên dùng):
```bash
# 1. Clone repository
git clone https://github.com/videoveo3pro-debug/pia.git /root/pia
cd /root/pia/prod

# 2. Điền thông tin tài khoản PIA (Dòng 1: Username, Dòng 2: Password)
nano credentials/pia_account_1

# 3. Chạy lệnh cài đặt và khởi động toàn bộ hệ thống
sudo bash deploy.sh
```

---

## 🛠️ Công Cụ Giám Sát & Kiểm Thử

- **Kiểm tra trạng thái toàn bộ pool proxy:**
  ```bash
  python3 prod/check_proxy.sh
  ```
- **Kiểm tra kết nối qua Gateway:**
  ```bash
  curl -x socks5h://proxy_user:proxy_password_secure123@127.0.0.1:1087 https://api.ipify.org
  ```
- **API Status:** `http://127.0.0.1:8007/api/status`
- **Web Dashboard:** `http://<IP_SERVER>:8007/`
- **HAProxy Live Stats:** `http://<IP_SERVER>:8411/`
