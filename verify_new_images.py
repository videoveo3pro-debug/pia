import pexpect
import base64
import time

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=700, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

restart_and_bench = """#!/bin/bash
set -e
cd /root/pia/prod

# Recreate all containers with the new pulled images
docker compose down
docker compose up -d

echo "Waiting 8s for containers to boot..."
sleep 8

# Connect all 16 workers
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16; do
  docker exec pia-worker-$i piactl --timeout 30 login /app/credentials/pia_account_1 >/dev/null 2>&1 || true
  docker exec pia-worker-$i piactl --timeout 30 connect >/dev/null 2>&1 || true
  sleep 0.5
done

sleep 5

echo "=== KIEM TRA TRANG THAI HEALTHZ CUA CAC WORKERS ==="
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16; do
  http_code=$(docker exec pia-worker-$i curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:9000/healthz 2>/dev/null || echo "ERR")
  st=$(docker exec pia-worker-$i piactl get connectionstate 2>/dev/null || echo "Unknown")
  ip=$(docker exec pia-worker-$i piactl get vpnip 2>/dev/null | tr -d '\r\n' || echo "Unknown")
  echo "Worker $i: State=$st | /healthz HTTP $http_code | IP=$ip"
done
"""

b64 = base64.b64encode(restart_and_bench.encode()).decode()
child.sendline(f"echo '{b64}' | base64 -d > /tmp/check_new.sh && bash /tmp/check_new.sh")
child.expect('=== KIEM TRA TRANG THAI HEALTHZ CUA CAC WORKERS ===', timeout=300)
print(child.before)
child.expect('root@', timeout=60)
print(child.before)
child.close()
