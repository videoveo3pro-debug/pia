import pexpect
import base64
import time

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=700, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

# 1. Connect all workers script
connect_all_py = """
import subprocess, time

print("=== CONNECTING WORKERS & CHECKING STATUS ===")
for i in range(1, 17):
    # Check connection
    res = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "connectionstate"], capture_output=True, text=True)
    st = res.stdout.strip()
    if st != "Connected":
        subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "--timeout", "30", "login", "/app/credentials/pia_account_1"], capture_output=True)
        subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "--timeout", "30", "connect"], capture_output=True)
        time.sleep(0.5)

time.sleep(3)
for i in range(1, 17):
    res_st = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "connectionstate"], capture_output=True, text=True)
    res_ip = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "vpnip"], capture_output=True, text=True)
    res_hc = subprocess.run(["docker", "exec", f"pia-worker-{i}", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://127.0.0.1:9000/healthz"], capture_output=True, text=True)
    print(f"Worker {i:02d}: State={res_st.stdout.strip()} | Healthz=HTTP {res_hc.stdout.strip()} | IP={res_ip.stdout.strip()}")
"""

b64_c = base64.b64encode(connect_all_py.encode()).decode()
child.sendline(f"echo '{b64_c}' | base64 -d > /tmp/conn_all.py && python3 /tmp/conn_all.py")
child.expect('Worker 16:', timeout=180)
print(child.before)
child.expect('root@', timeout=60)
print(child.before)

# 2. 100-request benchmark
bench_100_py = """
import subprocess, time, collections, statistics, datetime

TOTAL_REQUESTS = 100
INTERVAL_SECONDS = 3.0
PROXY_URL = "socks5h://proxy_user:proxy_password@127.0.0.1:1087"
TARGET_URL = "https://api.ipify.org"
HOST_IP = "103.82.193.113"

print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] === BAT DAU TEST 100 REQUESTS (KHOANG CACH 3S) - ZERO LEAK GUARANTEED ===")

ips = []
latencies = []
failures = []
leaked_host_ip = 0
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
                status_str = f"LEAK HOST IP ({ip}) - CRITICAL FAILURE! Latency: {dur}ms"
                failures.append((i, "HOST_IP_LEAK"))
            else:
                ips.append(ip)
                latencies.append(dur)
                status_str = f"OK (VPN IP: {ip}, Latency: {dur}ms)"
        else:
            err_msg = res.stderr.strip() or f"rc={res.returncode}"
            failures.append((i, err_msg))
            status_str = f"QUEUE DELAY / REJECT ({err_msg}, Latency: {dur}ms)"
    except Exception as e:
        failures.append((i, str(e)))
        status_str = f"TIMEOUT / ERROR ({e})"
    
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Req #{i:03d}/100: {status_str}", flush=True)
    
    if i < TOTAL_REQUESTS:
        time.sleep(INTERVAL_SECONDS)

total_elapsed = round(time.time() - start_time, 1)

print("\\n" + "="*65)
print("=== THONG KE KET QUA TEST 100 REQUESTS (16 WORKERS - ZERO LEAK) ===")
print("="*65)
print(f"Tong so requests: {TOTAL_REQUESTS}")
print(f"Thanh cong (VPN IP hop le): {len(ips)}/{TOTAL_REQUESTS} ({len(ips)/TOTAL_REQUESTS*100:.1f}%)")
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

b64_b = base64.b64encode(bench_100_py.encode()).decode()
child.sendline(f"echo '{b64_b}' | base64 -d > /tmp/run_100.py && python3 /tmp/run_100.py && echo '=== RESOURCE STATS ===' && free -h && uptime")
child.expect('=== RESOURCE STATS ===', timeout=650)
print(child.before)
child.expect('root@', timeout=60)
print(child.before)
child.close()
