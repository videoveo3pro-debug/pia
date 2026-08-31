import pexpect
import base64
import time

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=180, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

script = """
import subprocess, time

print("Connecting any disconnected workers...")
for i in range(1, 21):
    res_hc = subprocess.run(["docker", "exec", f"pia-worker-{i}", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://127.0.0.1:9000/healthz"], capture_output=True, text=True)
    if res_hc.stdout.strip() != "200":
        print(f"Connecting Worker {i:02d}...")
        subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "--timeout", "30", "login", "/app/credentials/pia_account_1"], capture_output=True)
        subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "--timeout", "30", "connect"], capture_output=True)
        time.sleep(1)

time.sleep(3)
print("=== FINAL 20 WORKERS STATUS ===")
for i in range(1, 21):
    res_st = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "connectionstate"], capture_output=True, text=True)
    res_ip = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "vpnip"], capture_output=True, text=True)
    res_hc = subprocess.run(["docker", "exec", f"pia-worker-{i}", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://127.0.0.1:9000/healthz"], capture_output=True, text=True)
    st = res_st.stdout.strip() or "Unknown"
    ip = res_ip.stdout.strip() or "Unknown"
    hc = res_hc.stdout.strip() or "ERR"
    print(f"Worker {i:02d}: State={st} | Healthz=HTTP {hc} | IP={ip}")
"""

b64 = base64.b64encode(script.encode()).decode()
child.sendline(f"echo '{b64}' | base64 -d > /tmp/finish_conn.py && python3 /tmp/finish_conn.py && free -h && uptime")
child.expect('Worker 20:', timeout=180)
print(child.before)
child.expect('root@', timeout=60)
print(child.before)
child.close()
