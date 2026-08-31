import pexpect

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=120, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

script = """
import subprocess

print("=== CHECKING 20 WORKERS STATUS ===")
for i in range(1, 21):
    res_st = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "connectionstate"], capture_output=True, text=True)
    res_ip = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "vpnip"], capture_output=True, text=True)
    res_hc = subprocess.run(["docker", "exec", f"pia-worker-{i}", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://127.0.0.1:9000/healthz"], capture_output=True, text=True)
    st = res_st.stdout.strip() or "Unknown"
    ip = res_ip.stdout.strip() or "Unknown"
    hc = res_hc.stdout.strip() or "ERR"
    print(f"Worker {i:02d}: State={st} | Healthz=HTTP {hc} | IP={ip}")
"""

import base64
b64 = base64.b64encode(script.encode()).decode()
child.sendline(f"echo '{b64}' | base64 -d > /tmp/check20.py && python3 /tmp/check20.py && free -h && uptime")
child.expect('Worker 20:', timeout=120)
print(child.before)
child.expect('root@', timeout=60)
print(child.before)
child.close()
