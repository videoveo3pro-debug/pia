import pexpect

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=120, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

script = """
import subprocess, time

for i in [17, 18, 19, 20]:
    print(f"=== ENABLING BACKGROUND & CONNECTING WORKER {i} ===")
    subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "background", "enable"], capture_output=True)
    time.sleep(1)
    res2 = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "connect"], capture_output=True, text=True)
    print(f"W{i} Connect:", res2.stdout.strip(), res2.stderr.strip())
    time.sleep(2)
    res3 = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "connectionstate"], capture_output=True, text=True)
    res_ip = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "vpnip"], capture_output=True, text=True)
    res_hc = subprocess.run(["docker", "exec", f"pia-worker-{i}", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://127.0.0.1:9000/healthz"], capture_output=True, text=True)
    print(f"W{i} State: {res3.stdout.strip()} | Healthz: HTTP {res_hc.stdout.strip()} | IP: {res_ip.stdout.strip()}")
"""

import base64
b64 = base64.b64encode(script.encode()).decode()
child.sendline(f"echo '{b64}' | base64 -d > /tmp/enable_bg.py && python3 /tmp/enable_bg.py")
child.expect('W20 State:', timeout=120)
print(child.before)
child.expect('root@', timeout=30)
print(child.before)
child.close()
