import pexpect
import base64
import time

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=600, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

deploy_20_sh = """#!/bin/bash
set -e
cd /root/pia
git pull origin main
cd prod

echo "Recreating 20 workers cluster..."
docker compose down
docker compose up -d

echo "Waiting 8s for containers to start..."
sleep 8

# Connect all 20 workers sequentially
for i in $(seq 1 20); do
  echo -n "Connecting W$i... "
  docker exec pia-worker-$i piactl --timeout 30 login /app/credentials/pia_account_1 >/dev/null 2>&1 || true
  docker exec pia-worker-$i piactl --timeout 30 connect >/dev/null 2>&1 || true
  sleep 0.5
  echo "OK"
done

sleep 5
echo "=== 20 WORKERS HEALTH STATUS ==="
for i in $(seq 1 20); do
  code=$(docker exec pia-worker-$i curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:9000/healthz 2>/dev/null || echo "ERR")
  st=$(docker exec pia-worker-$i piactl get connectionstate 2>/dev/null || echo "Unknown")
  ip=$(docker exec pia-worker-$i piactl get vpnip 2>/dev/null | tr -d '\r\n' || echo "Unknown")
  echo "Worker $i: State=$st | Healthz=HTTP $code | IP=$ip"
done
"""

b64 = base64.b64encode(deploy_20_sh.encode()).decode()
child.sendline(f"echo '{b64}' | base64 -d > /tmp/deploy_20.sh && bash /tmp/deploy_20.sh")
child.expect('=== 20 WORKERS HEALTH STATUS ===', timeout=300)
print(child.before)
child.expect('root@', timeout=60)
print(child.before)
child.close()
