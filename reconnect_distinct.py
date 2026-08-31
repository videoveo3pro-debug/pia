import pexpect

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=180, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

script = """
import subprocess, time, random

# 1. Lay danh sach tat ca cac regions tu PIA
res_regions = subprocess.run(["docker", "exec", "pia-worker-1", "piactl", "get", "regions"], capture_output=True, text=True)
all_regions = [r.strip() for r in res_regions.stdout.splitlines() if r.strip() and r.strip() != "auto"]
if not all_regions:
    all_regions = ["singapore", "japan", "us-california", "us-new-york", "germany", "uk-london", "france", "netherlands", "australia", "taiwan", "canada-ontario", "sweden", "switzerland", "brazil", "spain", "italy", "poland", "albania", "uruguay", "armenia"]

random.shuffle(all_regions)

# 2. Connect tung worker voi 1 region doc lap duy nhat
for i in range(1, 21):
    target = all_regions[(i - 1) % len(all_regions)]
    print(f"Connecting Worker {i:02d} -> {target}...")
    subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "--timeout", "30", "login", "/app/credentials/pia_account_1"], capture_output=True)
    subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "background", "enable"], capture_output=True)
    subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "--timeout", "30", "set", "region", target], capture_output=True)
    subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "--timeout", "30", "connect"], capture_output=True)
    time.sleep(1)

time.sleep(6)
print("=== CHECK 20 WORKERS FINAL STATUS ===")
for i in range(1, 21):
    res_ip = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "vpnip"], capture_output=True, text=True)
    res_reg = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "region"], capture_output=True, text=True)
    res_st = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "connectionstate"], capture_output=True, text=True)
    res_hc = subprocess.run(["docker", "exec", f"pia-worker-{i}", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://127.0.0.1:9000/healthz"], capture_output=True, text=True)
    print(f"Worker {i:02d}: IP={res_ip.stdout.strip():<16} | Region={res_reg.stdout.strip():<24} | Healthz={res_hc.stdout.strip()} | State={res_st.stdout.strip()}")
"""

import base64
b64 = base64.b64encode(script.encode()).decode()
child.sendline(f"echo '{b64}' | base64 -d > /tmp/reconnect_all_distinct.py && python3 /tmp/reconnect_all_distinct.py")
child.expect('Worker 20:', timeout=180)
print(child.before)
child.expect('root@', timeout=30)
print(child.before)
child.close()
