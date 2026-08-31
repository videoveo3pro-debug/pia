import pexpect
import base64
import time

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=600, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

deploy_sh = """#!/bin/bash
set -e
cd /root/pia
git pull origin main
cd prod

# Recreate containers with new HAProxy strict check & 20s queue delay
docker compose down
docker compose up -d

echo "Waiting 8s for containers to start..."
sleep 8

# Connect all 16 workers cleanly
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16; do
  echo "Connecting W$i..."
  docker exec pia-worker-$i piactl --timeout 30 login /app/credentials/pia_account_1 >/dev/null 2>&1 || true
  docker exec pia-worker-$i piactl --timeout 30 connect >/dev/null 2>&1 || true
  sleep 0.5
done

sleep 5
echo "=== 16 WORKERS VPN STATUS ==="
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16; do
  echo -n "Worker $i: "
  docker exec pia-worker-$i piactl get connectionstate 2>/dev/null || echo "Unknown"
  echo -n " -> IP: "
  docker exec pia-worker-$i piactl get vpnip 2>/dev/null || echo "Unknown"
done
"""

b64 = base64.b64encode(deploy_sh.encode()).decode()
child.sendline(f"echo '{b64}' | base64 -d > /tmp/deploy_strict.sh && bash /tmp/deploy_strict.sh")
child.expect('=== 16 WORKERS VPN STATUS ===', timeout=300)
print(child.before)
child.expect('root@', timeout=60)
print(child.before)
child.close()
