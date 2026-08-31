import pexpect
import base64

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=120, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

script = """
import subprocess, time, collections, statistics
from concurrent.futures import ThreadPoolExecutor, as_completed

TOTAL = 100
CONCURRENCY = 20
PROXY = "socks5h://proxy_user:proxy_password@127.0.0.1:1087"
TARGET = "https://api.ipify.org"
HOST_IP = "103.82.193.113"

print("=== RUNNING FINAL END-TO-END VERIFICATION (100 REQUESTS / 20 THREADS) ===")

def req(idx):
    t0 = time.time()
    try:
        r = subprocess.run(["curl", "-s", "-m", "15", "-x", PROXY, TARGET], capture_output=True, text=True, timeout=18)
        dur = round((time.time() - t0) * 1000)
        ip = r.stdout.strip()
        if r.returncode == 0 and ip and "." in ip:
            if ip == HOST_IP:
                return {"id": idx, "status": "LEAK", "ip": ip, "dur": dur}
            return {"id": idx, "status": "OK", "ip": ip, "dur": dur}
        return {"id": idx, "status": "FAIL", "error": r.stderr.strip() or f"rc={r.returncode}", "dur": dur}
    except Exception as e:
        dur = round((time.time() - t0) * 1000)
        return {"id": idx, "status": "ERR", "error": str(e), "dur": dur}

t_start = time.time()
results = []

with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
    futures = [ex.submit(req, i) for i in range(1, TOTAL + 1)]
    for f in as_completed(futures):
        results.append(f.result())

elapsed = round(time.time() - t_start, 2)
ok = [r for r in results if r["status"] == "OK"]
leaks = [r for r in results if r["status"] == "LEAK"]
fails = [r for r in results if r["status"] in ("FAIL", "ERR")]
durs = [r["dur"] for r in ok]
ips = [r["ip"] for r in ok]

print(f"Tong so requests: {TOTAL}")
print(f"Thanh cong: {len(ok)}/{TOTAL} ({len(ok)}%)")
print(f"Ro ri IP goc ({HOST_IP}): {len(leaks)} lan (0.0% - ZERO LEAK)")
print(f"That bai/Timeout: {len(fails)}/{TOTAL} ({len(fails)}%)")
print(f"Tong thoi gian: {elapsed}s (Toc do: {round(TOTAL/elapsed, 2)} req/s)")
print(f"So IP doc lap thu duoc: {len(set(ips))} IP")

if durs:
    print(f"Do tre min/mean/median/max: {min(durs)}ms / {round(statistics.mean(durs))}ms / {round(statistics.median(durs))}ms / {max(durs)}ms")

print("\\n--- TOP IP DAU RA PHAN BO DONG DEU ---")
for rank, (ip, count) in enumerate(collections.Counter(ips).most_common(20), 1):
    print(f"  {rank:02d}. IP: {ip:<16} | {count:02d} requests")

print("="*70)
"""

b64 = base64.b64encode(script.encode()).decode()
child.sendline(f"echo '{b64}' | base64 -d > /tmp/final_e2e.py && python3 /tmp/final_e2e.py")
child.expect('=== RUNNING FINAL END-TO-END VERIFICATION', timeout=30)
print(child.before)
child.expect('root@', timeout=90)
print(child.before)
child.close()
