# PIA SOCKS5 Multi-Worker Gateway

Bản refactor này chuyển từ mô hình **1 container proxy** sang mô hình:

```text
App khác
  -> socks5://proxy_user:proxy_password@127.0.0.1:1087
  -> HAProxy gateway
  -> vpn-worker-1 ... vpn-worker-8
```

Mục tiêu chính:

- Chạy cùng lúc tới 20 container PIA, trong đó mode runtime chọn 8, 16 hoặc 20 worker active.
- Mỗi worker có thể giữ một IP public khác nhau (lên tới 20 IP đồng thời).
- App bên ngoài chỉ dùng **một proxy cố định**.
- Khi một worker down/rotate, gateway loại worker đó khỏi pool và route request mới sang worker còn sống.
- Rotate theo từng container, không còn rotate global mơ hồ.

## Chạy nhanh

```bash
cp .env.example .env
mkdir -p credentials gateway/runtime
docker compose up -d --build
```

Sau khi container chạy, mở UI và login bằng account PIA dạng `username|password`.
Nếu checkbox `Lưu account` đang bật, credential sẽ được lưu trong `credentials/` để dùng
lại sau khi recreate/restart container. Không lưu credential trong `.env`.

Mặc định `docker compose` sẽ tự build image local. Nếu muốn pull image đã push sẵn, hãy set `BACKEND_IMAGE` và `WORKER_IMAGE` trong `.env`.

`credentials/` được mount vào backend và toàn bộ worker để lưu token, metrics và lịch sử IP qua các lần recreate container.

Mở dashboard/API:

```text
http://127.0.0.1:8007/
```

## Chế độ worker

```bash
docker compose up -d --build
```

Chọn chế độ 8, 16 hoặc 20 worker trực tiếp trên dashboard. Mặc định toàn bộ worker
dùng account 1; chỉ dùng account 2 nếu tự cấu hình `PROXY_WORKERS` với token_slot 2. Auto-rotate có thể dùng floor riêng, ví dụ
`AUTO_ROTATE_MIN_READY_WORKERS=8`, để vẫn ưu tiên rotate khi pool chưa đầy.

Proxy cho app khác:

```text
socks5://proxy_user:proxy_password@127.0.0.1:1087
```

## Các service chính

```text
proxy-gateway   -> HAProxy TCP gateway, expose port 1087
vpn-worker-1..20 -> PIA CLI + microsocks + control API
backend        -> FastAPI orchestrator/API/UI
```

## API mới

```http
GET  /api/nodes
GET  /api/nodes/healthy
GET  /api/nodes/{node_id}
POST /api/nodes/{node_id}/rotate
POST /api/nodes/{node_id}/recover
POST /api/nodes/{node_id}/disable
POST /api/nodes/{node_id}/enable
POST /api/recover
POST /api/rotate-any
POST /api/sessions/{session_id}/rotate
```

Ví dụ rotate một worker:

```bash
curl -X POST http://127.0.0.1:8007/api/nodes/worker1/rotate \
  -H "Content-Type: application/json" \
  -d '{"country":"Japan","wait_for_ready":false}'
```

Rotate bất kỳ worker nào phía sau gateway:

```bash
curl -X POST http://127.0.0.1:8007/api/rotate-any \
  -H "Content-Type: application/json" \
  -d '{"wait_for_ready":false}'
```

## Cơ chế mượt khi đổi IP

Khi rotate worker:

```text
worker READY
  -> backend disable worker khỏi HAProxy
  -> HAProxy không route request mới vào worker đó nữa
  -> worker disconnect/connect PIA
  -> backend check IP mới qua chính SOCKS5 worker
  -> nếu OK thì enable lại worker vào HAProxy
```

Trong lúc worker đó đang đổi IP, các worker còn lại vẫn online. Vì vậy app ngoài vẫn dùng cùng một proxy gateway.

## Giới hạn kỹ thuật

Gateway chuyển mượt cho **request/connection mới**. TCP/SOCKS connection đang mở dở không thể migrate 100% sang container khác. Với request HTTP ngắn và retry ở app ngoài, failover thường nằm trong mục tiêu dưới 10 giây.

## Cấu hình worker

Trong `.env`:

```env
# Default startup is random for every worker.
# Set WORKER_X_COUNTRY only when you want a fixed startup country.
# WORKER_1_COUNTRY=Japan
MIN_READY_WORKERS=3
GATEWAY_TARGET_FAILOVER_SECONDS=10
```

Không rotate cả 8 worker cùng lúc. Nên luôn giữ ít nhất 3 worker READY.


## Tự phục hồi worker

Bản này có watchdog để đưa pool về trạng thái 8/8 READY khi có thể:

```text
worker lỗi -> disable khỏi HAProxy -> reconnect PIA
          -> nếu vẫn lỗi: restart worker qua control API
          -> nếu control API mất: Docker restart đúng container
          -> check SOCKS5 + IP OK -> enable lại HAProxy
```

Biến cấu hình chính:

```env
HEALTH_INTERVAL_SECONDS=5
WORKER_RECOVERY_ENABLED=true
WORKER_RECOVERY_CONNECT_AFTER_FAILURES=1
WORKER_RECOVERY_RESTART_AFTER_FAILURES=3
WORKER_RECOVERY_DOCKER_RESTART_AFTER_FAILURES=5
WORKER_RECOVERY_COOLDOWN_SECONDS=15
READY_PROXY_FAILURE_FAIL_FAST=true
DOCKER_RECOVERY_ENABLED=true
```

Kích hoạt recover thủ công:

```bash
curl -X POST http://127.0.0.1:8007/api/recover \
  -H "Content-Type: application/json" \
  -d '{"force":false}'
```
