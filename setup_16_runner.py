import pexpect
import base64
import time

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=300, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

setup_sh = """#!/bin/bash
set -e
cd /root/pia/prod
sed -i 's/WORKER_COUNT=.*/WORKER_COUNT=16/g' .env
sed -i 's/MAX_WORKER_COUNT=.*/MAX_WORKER_COUNT=16/g' .env

# Stop workers 17..24
docker stop pia-worker-17 pia-worker-18 pia-worker-19 pia-worker-20 pia-worker-21 pia-worker-22 pia-worker-23 pia-worker-24 2>/dev/null || true

# Start workers 1..16
docker compose up -d vpn-worker-1 vpn-worker-2 vpn-worker-3 vpn-worker-4 vpn-worker-5 vpn-worker-6 vpn-worker-7 vpn-worker-8 vpn-worker-9 vpn-worker-10 vpn-worker-11 vpn-worker-12 vpn-worker-13 vpn-worker-14 vpn-worker-15 vpn-worker-16 proxy-gateway backend

echo 'Waiting 5s...'
sleep 5

# Connect all 16 workers
for i in $(seq 1 16); do
  st=$(docker exec pia-worker-$i piactl get connectionstate 2>/dev/null || true)
  if [ "$st" != "Connected" ]; then
    echo "Connecting W$i..."
    docker exec pia-worker-$i piactl --timeout 25 login /app/credentials/pia_account_1 >/dev/null 2>&1 || true
    docker exec pia-worker-$i piactl --timeout 25 connect >/dev/null 2>&1 || true
  fi
done

sleep 4
echo "=== STATUS 16 WORKERS ==="
for i in $(seq 1 16); do
  echo -n "Worker $i: "
  docker exec pia-worker-$i piactl get connectionstate 2>/dev/null || echo "Unknown"
  echo -n " -> IP: "
  docker exec pia-worker-$i piactl get vpnip 2>/dev/null || echo "Unknown"
done
"""

b64 = base64.b64encode(setup_sh.encode()).decode()
child.sendline(f"echo '{b64}' | base64 -d > /tmp/setup_16.sh && bash /tmp/setup_16.sh")
child.expect('=== STATUS 16 WORKERS ===', timeout=300)
print(child.before)
child.expect('root@', timeout=60)
print(child.before)
child.close()
