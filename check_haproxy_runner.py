import pexpect

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=60, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

script = """
import subprocess

res = subprocess.run(['docker', 'exec', 'pia-proxy-gateway', 'sh', '-c', 'echo "show stat" | socat stdio /run/haproxy/admin.sock'], capture_output=True, text=True)
lines = res.stdout.strip().splitlines()
print("=== HAPROXY SERVERS STATUS ===")
up_count = 0
down_count = 0
for l in lines:
    parts = l.split(',')
    if len(parts) > 17 and parts[0] == 'socks5_in':
        name = parts[1]
        status = parts[17]
        check_status = parts[36] if len(parts) > 36 else ""
        reqs = parts[4] if len(parts) > 4 else ""
        if status == "UP":
            up_count += 1
        elif status == "DOWN":
            down_count += 1
        print(f"{name:<16}: Status={status:<6} | Check={check_status:<16} | Reqs={reqs}")

print(f"\\nTong so backend UP: {up_count} | DOWN: {down_count}")
"""

import base64
b64 = base64.b64encode(script.encode()).decode()
child.sendline(f"echo '{b64}' | base64 -d > /tmp/check_haproxy.py && python3 /tmp/check_haproxy.py")
child.expect('Tong so backend UP:', timeout=30)
print(child.before)
child.expect('root@', timeout=30)
print(child.before)
child.close()
