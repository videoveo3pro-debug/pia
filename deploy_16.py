import pexpect
import base64
import time

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=300, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

deploy_sh = """#!/bin/bash
set -e
cd /root/pia
git pull origin main
cd prod

# Clean up all containers
docker compose down

# Start fresh with exactly 16 workers
docker compose up -d

echo "Waiting 10s for services to stabilize..."
sleep 10

# Connect all 16 workers sequentially to avoid CPU lock
for i in $(seq 1 16); do
  echo "Connecting Worker $i..."
  docker exec pia-worker-$i piactl --timeout 30 login /app/credentials/pia_account_1 >/dev/null 2>&1 || true
  docker exec pia-worker-$i piactl --timeout 30 connect >/dev/null 2>&1 || true
  sleep 1
done

sleep 5
echo "=== TRANG THAI 16 WORKERS ==="
for i in $(seq 1 16); do
  echo -n "Worker $i: "
  docker exec pia-worker-$i piactl get connectionstate 2>/dev/null || echo "Unknown"
  echo -n " -> IP: "
  docker exec pia-worker-$i piactl get vpnip 2>/dev/null || echo "Unknown"
done
"""

b64 = base64.b64encode(deploy_sh.encode()).decode()
child.sendline(f"echo '{b64}' | base64 -d > /tmp/deploy16.sh && bash /tmp/deploy16.sh")
child.expect('=== TRANG THAI 16 WORKERS ===', timeout=300)
print(child.before)
child.expect('root@', timeout=60)
print(child.before)
child.close()
