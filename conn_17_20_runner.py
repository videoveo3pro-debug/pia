import pexpect

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=120, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

script = """
import subprocess, time

for i in [17, 18, 19, 20, 3]:
    print(f"=== CONNECTING WORKER {i} ===")
    res1 = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "login", "/app/credentials/pia_account_1"], capture_output=True, text=True)
    print(f"W{i} Login:", res1.stdout.strip(), res1.stderr.strip())
    res2 = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "connect"], capture_output=True, text=True)
    print(f"W{i} Connect:", res2.stdout.strip(), res2.stderr.strip())
    time.sleep(2)
    res3 = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "connectionstate"], capture_output=True, text=True)
    print(f"W{i} State:", res3.stdout.strip())
"""

import base64
b64 = base64.b64encode(script.encode()).decode()
child.sendline(f"echo '{b64}' | base64 -d > /tmp/conn_17_20.py && python3 /tmp/conn_17_20.py")
child.expect('W20 State:', timeout=120)
print(child.before)
child.expect('root@', timeout=30)
print(child.before)
child.close()
