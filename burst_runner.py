import pexpect
import base64
import time

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=300, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

burst_script = """
import subprocess, time, collections, statistics, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

TOTAL_REQUESTS = 100
CONCURRENCY = 16
PROXY_URL = "socks5h://proxy_user:proxy_password@127.0.0.1:1087"
TARGET_URL = "https://api.ipify.org"
HOST_IP = "103.82.193.113"

print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] === BAT DAU GUI LIEN TUC 100 REQUESTS (BURST CONCURRENT 16 THREADS) ===")

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

with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
    futures = [executor.submit(send_req, i) for i in range(1, TOTAL_REQUESTS + 1)]
    for future in as_completed(futures):
        res = future.result()
        results.append(res)
        if res["status"] == "OK":
            print(f"Req #{res['id']:03d}: OK (VPN IP: {res['ip']}, {res['dur']}ms)", flush=True)
        elif res["status"] == "LEAK":
            print(f"Req #{res['id']:03d}: LEAK HOST IP ({res['ip']}) - FAILED!", flush=True)
        else:
            print(f"Req #{res['id']:03d}: FAILED/DELAY ({res.get('error')}, {res['dur']}ms)", flush=True)

total_elapsed = round(time.time() - start_time, 2)

successful = [r for r in results if r["status"] == "OK"]
leaked = [r for r in results if r["status"] == "LEAK"]
failed = [r for r in results if r["status"] in ("FAIL", "ERR")]
latencies = [r["dur"] for r in successful]
ips = [r["ip"] for r in successful]
rps = round(TOTAL_REQUESTS / total_elapsed, 2) if total_elapsed > 0 else 0

print("\\n" + "="*65)
print("=== THONG KE KET QUA GUI LIEN TUC 100 REQUESTS (BURST MODE) ===")
print("="*65)
print(f"Tong so requests gui: {TOTAL_REQUESTS} requests (16 luong dong thoi)")
print(f"Thanh cong (VPN IP hop le): {len(successful)}/{TOTAL_REQUESTS} ({len(successful)/TOTAL_REQUESTS*100:.1f}%)")
print(f"Ro ri IP goc ({HOST_IP}): {len(leaked)} lan (0.0% - TUYET DOI KHONG LEAK)")
print(f"That bai/Timeout: {len(failed)}/{TOTAL_REQUESTS}")
print(f"Tong thoi gian hoan thanh: {total_elapsed} giay")
print(f"Toc do xu ly (Throughput): {rps} requests/giay")
print(f"So IP VPN phan biet (Unique IPs): {len(set(ips))}")

if latencies:
    print(f"Do tre trung binh (Avg Latency): {round(statistics.mean(latencies))} ms")
    print(f"Do tre nho nhat (Min Latency): {min(latencies)} ms")
    print(f"Do tre lon nhat (Max Latency): {max(latencies)} ms")
    print(f"Trung vi (Median / P50): {round(statistics.median(latencies))} ms")

print("\\n--- BANG PHAN BO CAC IP VPN XUAT HIEN ---")
counter = collections.Counter(ips)
for rank, (ip_addr, count) in enumerate(counter.most_common(), 1):
    pct = (count / len(ips)) * 100 if ips else 0
    print(f"  {rank:02d}. IP: {ip_addr:<16} | {count:02d} lan ({pct:4.1f}%)")

print("="*65)
"""

b64 = base64.b64encode(burst_script.encode()).decode()
child.sendline(f"echo '{b64}' | base64 -d > /tmp/burst_100.py && python3 /tmp/burst_100.py && echo '=== SYSTEM RESOURCES AFTER BURST ===' && free -h && uptime")
child.expect('=== SYSTEM RESOURCES AFTER BURST ===', timeout=240)
print(child.before)
child.expect('root@', timeout=30)
print(child.before)
child.close()
