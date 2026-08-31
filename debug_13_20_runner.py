import pexpect

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=60, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

script = """
import subprocess, time

print("=== DETAILED DEBUG WORKER 13 TO 20 ===")
for i in [13, 14, 15, 16, 17, 18, 19, 20]:
    print(f"\\n--- WORKER {i} ---")
    st1 = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "connectionstate"], capture_output=True, text=True)
    print("Initial State:", st1.stdout.strip())
    
    bg = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "background", "enable"], capture_output=True, text=True)
    print("Background enable:", bg.stdout.strip(), bg.stderr.strip())

    log_res = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "login", "/app/credentials/pia_account_1"], capture_output=True, text=True)
    print("Login:", log_res.stdout.strip(), log_res.stderr.strip())

    conn_res = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "connect"], capture_output=True, text=True)
    print("Connect:", conn_res.stdout.strip(), conn_res.stderr.strip())

    time.sleep(2)
    st2 = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "connectionstate"], capture_output=True, text=True)
    ip_res = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "vpnip"], capture_output=True, text=True)
    print("New State:", st2.stdout.strip(), "| IP:", ip_res.stdout.strip())
"""

import base64
b64 = base64.b64encode(script.encode()).decode()
child.sendline(f"echo '{b64}' | base64 -d > /tmp/debug_13_20.py && python3 /tmp/debug_13_20.py")
child.expect('--- WORKER 20 ---', timeout=60)
print(child.before)
child.expect('root@', timeout=30)
print(child.before)
child.close()
