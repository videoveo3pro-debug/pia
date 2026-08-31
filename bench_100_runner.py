import pexpect
import base64
import time
import sys

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=600, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

# 1. Connect all 16 workers script
conn_sh = """#!/bin/bash
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16; do
  st=$(docker exec pia-worker-$i piactl get connectionstate 2>/dev/null || echo "Disconnected")
  if [ "$st" != "Connected" ]; then
    docker exec pia-worker-$i piactl --timeout 30 login /app/credentials/pia_account_1 >/dev/null 2>&1 || true
    docker exec pia-worker-$i piactl --timeout 30 connect >/dev/null 2>&1 || true
    sleep 0.5
  fi
done
sleep 4
echo "=== 16 WORKERS READY STATUS ==="
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16; do
  echo -n "W$i: "
  docker exec pia-worker-$i piactl get connectionstate 2>/dev/null
  echo -n " (IP: "
  docker exec pia-worker-$i piactl get vpnip 2>/dev/null | tr -d '\r\n'
  echo ")"
done
"""

b64_conn = base64.b64encode(conn_sh.encode()).decode()
child.sendline(f"echo '{b64_conn}' | base64 -d > /tmp/ensure_conn.sh && bash /tmp/ensure_conn.sh")
child.expect('=== 16 WORKERS READY STATUS ===', timeout=180)
print(child.before)
child.expect('root@', timeout=60)
print(child.before)

# 2. 100-request benchmark script (3s interval)
bench_100_py = """
import subprocess, time, collections, statistics, datetime

TOTAL_REQUESTS = 100
INTERVAL_SECONDS = 3.0
PROXY_URL = "socks5h://proxy_user:proxy_password@127.0.0.1:1087"
TARGET_URL = "https://api.ipify.org"

print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] === BAT DAU TEST 100 REQUESTS (KHOANG CACH 3S) QUA 16 WORKERS ===")

ips = []
latencies = []
failures = []
start_time = time.time()

for i in range(1, TOTAL_REQUESTS + 1):
    req_t0 = time.time()
    try:
        res = subprocess.run(
            ["curl", "-s", "-m", "7", "-x", PROXY_URL, TARGET_URL],
            capture_output=True, text=True, timeout=8
        )
        dur = round((time.time() - req_t0) * 1000)
        ip = res.stdout.strip()
        if res.returncode == 0 and ip and "." in ip:
            ips.append(ip)
            latencies.append(dur)
            status_str = f"OK (IP: {ip}, Latency: {dur}ms)"
        else:
            err_msg = res.stderr.strip() or f"rc={res.returncode}"
            failures.append((i, err_msg))
            status_str = f"FAILED ({err_msg})"
    except Exception as e:
        failures.append((i, str(e)))
        status_str = f"ERROR ({e})"
    
    # In ra tung request
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Req #{i:03d}/100: {status_str}", flush=True)
    
    if i < TOTAL_REQUESTS:
        time.sleep(INTERVAL_SECONDS)

total_elapsed = round(time.time() - start_time, 1)

print("\\n" + "="*60)
print("=== THONG KE KET QUA TEST 100 REQUESTS (16 WORKERS) ===")
print("="*60)
print(f"Tong so requests: {TOTAL_REQUESTS}")
print(f"Thanh cong: {len(ips)}/{TOTAL_REQUESTS} ({len(ips)/TOTAL_REQUESTS*100:.1f}%)")
print(f"That bai: {len(failures)}/{TOTAL_REQUESTS} ({len(failures)/TOTAL_REQUESTS*100:.1f}%)")
print(f"Tong thoi gian chay: {total_elapsed} giay (~{round(total_elapsed/60, 1)} phut)")
print(f"So IP VPN phan biet (Unique IPs): {len(set(ips))}")

if latencies:
    print(f"Do tre trung binh (Avg): {round(statistics.mean(latencies))} ms")
    print(f"Do tre nho nhat (Min): {min(latencies)} ms")
    print(f"Do tre lon nhat (Max): {max(latencies)} ms")
    print(f"Trung vi (Median / P50): {round(statistics.median(latencies))} ms")

print("\\n--- BANG PHAN BO CAC IP XUAT HIEN ---")
counter = collections.Counter(ips)
for rank, (ip_addr, count) in enumerate(counter.most_common(), 1):
    pct = (count / len(ips)) * 100 if ips else 0
    print(f"  {rank:02d}. IP: {ip_addr:<16} | {count:02d} lan ({pct:4.1f}%)")

print("="*60)
"""

b64_bench = base64.b64encode(bench_100_py.encode()).decode()
child.sendline(f"echo '{b64_bench}' | base64 -d > /tmp/bench_100.py && python3 /tmp/bench_100.py && echo '=== SYSTEM RESOURCES AFTER 100 REQS ===' && free -h && uptime")
child.expect('=== SYSTEM RESOURCES AFTER 100 REQS ===', timeout=600)
print(child.before)
child.expect('root@', timeout=60)
print(child.before)
child.close()
