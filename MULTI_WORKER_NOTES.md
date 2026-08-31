# Ghi chú refactor multi-worker

## Điểm đã đổi

- Thêm `proxy-gateway` dùng HAProxy, expose duy nhất port SOCKS5 host `PROXY_PORT`.
- Thêm 4 service worker: `vpn-worker-1..4`, mỗi worker chạy PIA CLI + microsocks + control API.
- Backend không còn điều khiển một proxy duy nhất, mà quản lý pool worker qua `PROXY_WORKERS`.
- Rotate IP theo từng worker qua `/api/nodes/{node_id}/rotate`.
- Rotate mượt qua `/api/rotate-any`: worker bị rotate sẽ bị disable khỏi HAProxy trước, các worker READY còn lại vẫn nhận traffic.
- Thêm HAProxy runtime socket `/run/haproxy/admin.sock` để backend enable/disable worker realtime.
- Dashboard hiển thị worker pool và trạng thái READY/DOWN.

## Luồng rotate worker

```text
POST /api/nodes/worker1/rotate
  -> disable server socks5_workers/worker1
  -> pia disconnect/connect bên trong worker1
  -> check IP qua socks5 của worker1
  -> nếu OK: enable server socks5_workers/worker1
  -> nếu lỗi: giữ worker1 disabled, request mới vẫn đi qua worker khác
```

## Lưu ý

- Mượt cho request/connection mới.
- TCP/SOCKS connection đang mở dở không thể migrate sang worker khác 100% trong suốt.
- Nên cấu hình app gọi proxy có retry 1-2 lần để failover luôn dưới khoảng 10 giây.
- Không rotate cả 8 worker cùng lúc. Giữ `MIN_READY_WORKERS=3`.


## Worker self-healing

Backend watchdog chạy mỗi `HEALTH_INTERVAL_SECONDS` giây. Worker nào không READY sẽ bị disable khỏi HAProxy, sau đó tự phục hồi theo tầng:

1. `pia connect` lại bằng country hint của worker.
2. Nếu lỗi liên tiếp >= `WORKER_RECOVERY_RESTART_AFTER_FAILURES`, gọi control API `/restart` để worker container tự exit và Docker restart lại.
3. Nếu control API không trả lời và lỗi liên tiếp >= `WORKER_RECOVERY_DOCKER_RESTART_AFTER_FAILURES`, backend gọi Docker API qua `/var/run/docker.sock` để restart đúng container.
4. Chỉ enable worker lại vào HAProxy khi control API OK, SOCKS5 listening, PIA connected và IP check qua chính worker OK.

API thủ công:

```bash
curl -X POST http://127.0.0.1:8002/api/recover \
  -H "Content-Type: application/json" \
  -d '{"force":false}'

curl -X POST http://127.0.0.1:8002/api/nodes/worker1/recover \
  -H "Content-Type: application/json" \
  -d '{"force":true}'
```
