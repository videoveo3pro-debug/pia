import pexpect

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=60, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

script = """
import subprocess

print("=== KIEM TRA CHINH XAC SO LUONG IP DANG ONLINE ===")

active_ips = []
unique_active_ips = set()
nodes_report = []

for i in range(1, 21):
    res_st = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "connectionstate"], capture_output=True, text=True)
    res_ip = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "vpnip"], capture_output=True, text=True)
    res_reg = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "region"], capture_output=True, text=True)
    res_hc = subprocess.run(["docker", "exec", f"pia-worker-{i}", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://127.0.0.1:9000/healthz"], capture_output=True, text=True)

    st = res_st.stdout.strip() or "Unknown"
    ip = res_ip.stdout.strip() or "Unknown"
    reg = res_reg.stdout.strip() or "Unknown"
    hc = res_hc.stdout.strip() or "ERR"

    is_online = (st == "Connected" and hc == "200" and ip != "Unknown" and "." in ip)
    if is_online:
        active_ips.append(ip)
        unique_active_ips.add(ip)
    
    nodes_report.append((f"worker{i}", ip, reg, st, hc, is_online))

print(f"\\nTong so Worker dang ONLINE va HEALTHY (HTTP 200): {len(active_ips)} / 20 Worker")
print(f"Tong so IP DOC LAP DUY NHAT dang hoat dong: {len(unique_active_ips)} IP\\n")

print("--- CHI TIET TRANG THAI TUNG WORKER ---")
for w, ip, reg, st, hc, online in nodes_report:
    status_icon = "🟢 ONLINE" if online else "🔴 OFFLINE"
    print(f"  {w:<9}: {status_icon:<10} | IP: {ip:<16} | Region: {reg:<25} | State: {st:<12} | Healthz: HTTP {hc}")

"""

import base64
b64 = base64.b64encode(script.encode()).decode()
child.sendline(f"echo '{b64}' | base64 -d > /tmp/check_live_ips.py && python3 /tmp/check_live_ips.py")
child.expect('=== KIEM TRA CHINH XAC SO LUONG IP DANG ONLINE ===', timeout=45)
print(child.before)
child.expect('root@', timeout=45)
print(child.before)
child.close()
