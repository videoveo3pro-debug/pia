import pexpect

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=180, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

script = """
import subprocess, time, random

res_regions = subprocess.run(["docker", "exec", "pia-worker-1", "piactl", "get", "regions"], capture_output=True, text=True)
all_regions = [r.strip() for r in res_regions.stdout.splitlines() if r.strip() and r.strip() != "auto"]
random.shuffle(all_regions)

for i in range(13, 21):
    target = all_regions[i]
    print(f"Connecting Worker {i:02d} -> {target}...")
    subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "--timeout", "30", "login", "/app/credentials/pia_account_1"], capture_output=True)
    subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "background", "enable"], capture_output=True)
    subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "--timeout", "30", "set", "region", target], capture_output=True)
    subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "--timeout", "30", "connect"], capture_output=True)
    time.sleep(1.5)

time.sleep(5)
print("=== FINAL 20 WORKERS IP CHECK ===")
for i in range(1, 21):
    res_ip = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "vpnip"], capture_output=True, text=True)
    res_reg = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "region"], capture_output=True, text=True)
    res_st = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "connectionstate"], capture_output=True, text=True)
    print(f"Worker {i:02d}: IP={res_ip.stdout.strip():<16} | Region={res_reg.stdout.strip():<24} | State={res_st.stdout.strip()}")
"""

import base64
b64 = base64.b64encode(script.encode()).decode()
child.sendline(f"echo '{b64}' | base64 -d > /tmp/finish_13_20.py && python3 /tmp/finish_13_20.py")
child.expect('Worker 20:', timeout=180)
print(child.before)
child.expect('root@', timeout=30)
print(child.before)
child.close()
