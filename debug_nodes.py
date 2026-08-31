import pexpect

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=60, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

script = """
import urllib.request, json, subprocess

req = urllib.request.urlopen("http://127.0.0.1:8007/api/status")
data = json.loads(req.read().decode())
print("Worker mode:", data.get("worker_mode"))
print("Active nodes count in status:", len([n for n in data.get("nodes", []) if n.get("active")]))
for n in data.get("nodes", []):
    print(f"{n['id']}: active={n.get('active')} ready={n.get('ready')} ip={n.get('current_ip')} region={n.get('region')}")
"""

import base64
b64 = base64.b64encode(script.encode()).decode()
child.sendline(f"echo '{b64}' | base64 -d > /tmp/debug_nodes.py && python3 /tmp/debug_nodes.py")
child.expect('worker20:', timeout=45)
print(child.before)
child.expect('root@', timeout=30)
print(child.before)
child.close()
