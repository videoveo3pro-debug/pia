import pexpect

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=60, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

script = """
import subprocess

print("=== FAST STATUS CHECK ===")
online_count = 0
for i in range(1, 21):
    try:
        r_st = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "connectionstate"], capture_output=True, text=True, timeout=2)
        st = r_st.stdout.strip() or "Unknown"
    except Exception:
        st = "Timeout"
    
    try:
        r_ip = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "vpnip"], capture_output=True, text=True, timeout=2)
        ip = r_ip.stdout.strip() or "Unknown"
    except Exception:
        ip = "Unknown"

    try:
        r_reg = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "region"], capture_output=True, text=True, timeout=2)
        reg = r_reg.stdout.strip() or "Unknown"
    except Exception:
        reg = "Unknown"

    is_on = (st == "Connected" and ip != "Unknown" and "." in ip)
    if is_on:
        online_count += 1
    icon = "🟢 ONLINE" if is_on else "🔴 OFFLINE"
    print(f"Worker {i:02d}: {icon:<9} | IP={ip:<16} | Region={reg:<25} | State={st}")

print(f"\\nTong so Worker ONLINE: {online_count} / 20 Worker")
"""

import base64
b64 = base64.b64encode(script.encode()).decode()
child.sendline(f"echo '{b64}' | base64 -d > /tmp/fast_check.py && python3 /tmp/fast_check.py")
child.expect('Tong so Worker ONLINE:', timeout=60)
print(child.before)
child.expect('root@', timeout=30)
print(child.before)
child.close()
