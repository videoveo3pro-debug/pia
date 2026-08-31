import pexpect
import base64
import time

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=700, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

# 1. Ensure all workers are connected
conn_script = """
for _ in 1 2; do
  for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16; do
    st=$(docker exec pia-worker-$i piactl get connectionstate 2>/dev/null || echo "Disconnected")
    if [ "$st" != "Connected" ]; then
      docker exec pia-worker-$i piactl --timeout 30 login /app/credentials/pia_account_1 >/dev/null 2>&1 || true
      docker exec pia-worker-$i piactl --timeout 30 connect >/dev/null 2>&1 || true
      sleep 0.5
    fi
  done
  sleep 3
done
echo "=== READY WORKERS CHECK ==="
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16; do
  echo -n "W$i: "
  docker exec pia-worker-$i piactl get connectionstate 2>/dev/null
  echo -n " (IP: "
  docker exec pia-worker-$i piactl get vpnip 2>/dev/null | tr -d '\r\n'
  echo ")"
done
"""
b64_c = base64.b64encode(conn_script.encode()).decode()
child.sendline(f"echo '{b64_c}' | base64 -d > /tmp/check_conn.sh && bash /tmp/check_conn.sh")
child.expect('=== READY WORKERS CHECK ===', timeout=180)
print(child.before)
child.expect('root@', timeout=60)
print(child.before)

# 2. Run 100-request benchmark test with 3s spacing
bench_100_script = """
import subprocess, time, collections, statistics, datetime

TOTAL_REQUESTS = 100
INTERVAL_SECONDS = 3.0
PROXY_URL = "socks5h://proxy_user:proxy_password@127.0.0.1:1087"
TARGET_URL = "https://api.ipify.org"

print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] === BAT DAU TEST 100 REQUESTS (KHOANG CACH 3S) - STRICT ZERO-LEAK MODE ===")

ips = []
latencies = []
failures = []
leaked_host_ip = 0
HOST_IP = "103.82.193.113"
start_time = time.time()

for i in range(1, TOTAL_REQUESTS + 1):
    req_t0 = time.time()
    try:
        res = subprocess.run(
            ["curl", "-s", "-m", "22", "-x", PROXY_URL, TARGET_URL],
            capture_output=True, text=True, timeout=25
        )
        dur = round((time.time() - req_t0) * 1000)
        ip = res.stdout.strip()
        if res.returncode == 0 and ip and "." in ip:
            if ip == HOST_IP:
                leaked_host_ip += 1
                status_str = f"LEAK HOST IP ({ip}) - FAILED! Latency: {dur}ms"
                failures.append((i, "HOST_IP_LEAK"))
            else:
                ips.append(ip)
                latencies.append(dur)
                status_str = f"OK (VPN IP: {ip}, Latency: {dur}ms)"
        else:
            err_msg = res.stderr.strip() or f"rc={res.returncode}"
            failures.append((i, err_msg))
            status_str = f"DELAY/DROP ({err_msg}, Latency: {dur}ms)"
    except Exception as e:
        failures.append((i, str(e)))
        status_str = f"TIMEOUT/ERROR ({e})"
    
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Req #{i:03d}/100: {status_str}", flush=True)
    
    if i < TOTAL_REQUESTS:
        time.sleep(INTERVAL_SECONDS)

total_elapsed = round(time.time() - start_time, 1)

print("\\n" + "="*65)
print("=== THONG KE KET QUA TEST 100 REQUESTS (16 WORKERS - ZERO LEAK) ===")
print("="*65)
print(f"Tong so requests: {TOTAL_REQUESTS}")
print(f"Thanh cong (VPN IP sach): {len(ips)}/{TOTAL_REQUESTS} ({len(ips)/TOTAL_REQUESTS*100:.1f}%)")
print(f"Ro ri IP goc ({HOST_IP}): {leaked_host_ip} lan ({leaked_host_ip/TOTAL_REQUESTS*100:.1f}%)")
print(f"That bai/Timeout: {len(failures) - leaked_host_ip}/{TOTAL_REQUESTS}")
print(f"Tong thoi gian chay: {total_elapsed} giay (~{round(total_elapsed/60, 1)} phut)")
print(f"So IP VPN phan biet (Unique IPs): {len(set(ips))}")

if latencies:
    print(f"Do tre trung binh (Avg Latency): {round(statistics.mean(latencies))} ms")
    print(f"Do tre nho nhat (Min Latency): {min(latencies)} ms")
    print(f"Do tre lon nhat (Max Latency): {max(latencies)} ms")
    print(f"Trung vi (Median Latency): {round(statistics.median(latencies))} ms")

print("\\n--- BANG PHAN BO CAC IP VPN XUAT HIEN ---")
counter = collections.Counter(ips)
for rank, (ip_addr, count) in enumerate(counter.most_common(), 1):
    pct = (count / len(ips)) * 100 if ips else 0
    print(f"  {rank:02d}. IP: {ip_addr:<16} | {count:02d} lan ({pct:4.1f}%)")

print("="*65)
"""
b64_b = base64.b64encode(bench_100_script.encode()).decode()
child.sendline(f"echo '{b64_b}' | base64 -d > /tmp/bench_100_strict.py && python3 /tmp/bench_100_strict.py && echo '=== SYSTEM RESOURCES AFTER TEST ===' && free -h && uptime")
child.expect('=== SYSTEM RESOURCES AFTER TEST ===', timeout=650)
print(child.before)
child.expect('root@', timeout=60)
print(child.before)
child.close()
