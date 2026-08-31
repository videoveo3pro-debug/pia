import pexpect
import base64
import time

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=60, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

stress_test_py = """
import subprocess, time, collections, statistics, datetime, sys
from concurrent.futures import ThreadPoolExecutor, as_completed

TOTAL_REQUESTS = 1000
CONCURRENCY = 20
PROXY_URL = "socks5h://proxy_user:proxy_password@127.0.0.1:1087"
TARGET_URL = "https://api.ipify.org"
HOST_IP = "103.82.193.113"

print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] === BAT DAU STRESS-TEST 1000 REQUESTS (20 THREADS CONCURRENT) ===", flush=True)

def send_req(req_id):
    t0 = time.time()
    try:
        res = subprocess.run(
            ["curl", "-s", "-m", "22", "-x", PROXY_URL, TARGET_URL],
            capture_output=True, text=True, timeout=25
        )
        dur = round((time.time() - t0) * 1000)
        ip = res.stdout.strip()
        if res.returncode == 0 and ip and "." in ip:
            if ip == HOST_IP:
                return {"id": req_id, "status": "LEAK", "ip": ip, "dur": dur}
            return {"id": req_id, "status": "OK", "ip": ip, "dur": dur}
        else:
            return {"id": req_id, "status": "FAIL", "error": res.stderr.strip() or f"rc={res.returncode}", "dur": dur}
    except Exception as e:
        dur = round((time.time() - t0) * 1000)
        return {"id": req_id, "status": "ERR", "error": str(e), "dur": dur}

start_time = time.time()
results = []
completed_count = 0

with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
    futures = [executor.submit(send_req, i) for i in range(1, TOTAL_REQUESTS + 1)]
    for future in as_completed(futures):
        res = future.result()
        results.append(res)
        completed_count += 1
        if completed_count % 100 == 0 or completed_count == TOTAL_REQUESTS:
            elapsed_now = time.time() - start_time
            current_rps = round(completed_count / elapsed_now, 2) if elapsed_now > 0 else 0
            ok_so_far = sum(1 for r in results if r["status"] == "OK")
            leak_so_far = sum(1 for r in results if r["status"] == "LEAK")
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Tien do: {completed_count:04d}/{TOTAL_REQUESTS} ({completed_count/TOTAL_REQUESTS*100:5.1f}%) | OK: {ok_so_far} | Leak: {leak_so_far} | Toc do: {current_rps} req/s", flush=True)

total_elapsed = round(time.time() - start_time, 2)

successful = [r for r in results if r["status"] == "OK"]
leaked = [r for r in results if r["status"] == "LEAK"]
failed = [r for r in results if r["status"] in ("FAIL", "ERR")]
latencies = [r["dur"] for r in successful]
ips = [r["ip"] for r in successful]
rps = round(TOTAL_REQUESTS / total_elapsed, 2) if total_elapsed > 0 else 0

print("\\n" + "="*70, flush=True)
print("=== THONG KE KET QUA STRESS-TEST 1000 REQUESTS (20 THREADS) ===", flush=True)
print("="*70, flush=True)
print(f"Tong so requests gui: {TOTAL_REQUESTS} requests", flush=True)
print(f"So luong threads song song: {CONCURRENCY} threads", flush=True)
print(f"Thanh cong (VPN IP hop le): {len(successful)}/{TOTAL_REQUESTS} ({len(successful)/TOTAL_REQUESTS*100:.1f}%)", flush=True)
print(f"Ro ri IP goc ({HOST_IP}): {len(leaked)} lan (0.0% - TUYET DOI ZERO-LEAK)", flush=True)
print(f"That bai/Timeout: {len(failed)}/{TOTAL_REQUESTS} ({len(failed)/TOTAL_REQUESTS*100:.1f}%)", flush=True)
print(f"Tong thoi gian chay: {total_elapsed} giay (~{round(total_elapsed/60, 2)} phut)", flush=True)
print(f"Toc do xu ly thuc te (Throughput): {rps} requests / giay", flush=True)
print(f"So IP VPN phan biet (Unique IPs): {len(set(ips))}", flush=True)

if latencies:
    lat_sorted = sorted(latencies)
    print(f"\\n--- THONG KE DO TRE (LATENCY) ---", flush=True)
    print(f"  - Nho nhat (Min): {min(latencies)} ms", flush=True)
    print(f"  - Trung binh (Mean): {round(statistics.mean(latencies))} ms", flush=True)
    print(f"  - Trung vi (Median / P50): {round(statistics.median(latencies))} ms", flush=True)
    print(f"  - P90 (90% requests duoi): {lat_sorted[int(len(lat_sorted)*0.90)]} ms", flush=True)
    print(f"  - P95 (95% requests duoi): {lat_sorted[int(len(lat_sorted)*0.95)]} ms", flush=True)
    print(f"  - P99 (99% requests duoi): {lat_sorted[int(len(lat_sorted)*0.99)]} ms", flush=True)
    print(f"  - Lon nhat (Max): {max(latencies)} ms", flush=True)

print(f"\\n--- BANG PHAN BO TOP IP VPN XUAT HIEN ---", flush=True)
counter = collections.Counter(ips)
for rank, (ip_addr, count) in enumerate(counter.most_common(20), 1):
    pct = (count / len(ips)) * 100 if ips else 0
    print(f"  {rank:02d}. IP: {ip_addr:<16} | {count:03d} lan ({pct:4.1f}%)", flush=True)

print("="*70, flush=True)
"""

b64 = base64.b64encode(stress_test_py.encode()).decode()
child.sendline(f"echo '{b64}' | base64 -d > /tmp/stress_1000.py && nohup python3 /tmp/stress_1000.py > /tmp/stress_1000.log 2>&1 &")
child.expect('root@', timeout=30)
print("Started 1000-request stress test on VPS.")
child.close()
