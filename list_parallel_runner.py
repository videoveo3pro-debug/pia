import pexpect

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=60, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

script = """
import subprocess

print("=== DANH SACH 20 IP SONG SONG DANG HOAT DONG ===")
online_count = 0
ips = []
for i in range(1, 21):
    r_st = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "connectionstate"], capture_output=True, text=True)
    r_ip = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "vpnip"], capture_output=True, text=True)
    r_reg = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "region"], capture_output=True, text=True)
    st = r_st.stdout.strip()
    ip = r_ip.stdout.strip()
    reg = r_reg.stdout.strip()
    is_on = (st == "Connected" and ip != "Unknown" and "." in ip)
    if is_on:
        online_count += 1
        ips.append(ip)
    icon = "🟢 ONLINE" if is_on else "🔴 OFFLINE"
    print(f"Worker {i:02d}: {icon:<9} | IP: {ip:<16} | Region: {reg:<25} | State: {st}")

print(f"\\nTong so IP song song dang san sang: {online_count} / 20 IP (Unique: {len(set(ips))})")
"""

import base64
b64 = base64.b64encode(script.encode()).decode()
child.sendline(f"echo '{b64}' | base64 -d > /tmp/list_parallel.py && python3 /tmp/list_parallel.py")
child.expect('Tong so IP song song', timeout=45)
print(child.before)
child.expect('root@', timeout=30)
print(child.before)
child.close()
