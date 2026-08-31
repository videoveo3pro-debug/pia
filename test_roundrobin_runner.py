import pexpect

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=60, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

script = """
import subprocess, time

# 1. Pull & recreate proxy-gateway
subprocess.run(["sh", "-c", "cd /root/pia && git pull origin main && cd prod && docker compose up -d proxy-gateway"])
time.sleep(2)

print("=== TEST 10 CONSECUTIVE REQUESTS (PER-REQUEST ROTATION) ===")
for i in range(1, 11):
    t0 = time.time()
    res = subprocess.run(["curl", "-s", "-m", "5", "-x", "socks5h://proxy_user:proxy_password@127.0.0.1:1087", "https://api.ipify.org"], capture_output=True, text=True)
    dur = round((time.time() - t0) * 1000)
    ip = res.stdout.strip()
    print(f"Request #{i:02d}: IP={ip:<16} ({dur}ms)")
    time.sleep(0.3)
"""

import base64
b64 = base64.b64encode(script.encode()).decode()
child.sendline(f"echo '{b64}' | base64 -d > /tmp/test_roundrobin.py && python3 /tmp/test_roundrobin.py")
child.expect('Request #10:', timeout=45)
print(child.before)
child.expect('root@', timeout=30)
print(child.before)
child.close()
