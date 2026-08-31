import pexpect

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=120, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

script = """
import subprocess, time, random

# 1. Lay token session hop le tu pia-worker-1
res_acc = subprocess.run(["docker", "exec", "pia-worker-1", "cat", "/opt/piavpn/etc/account.json"], capture_output=True, text=True)
valid_account_json = res_acc.stdout

res_regions = subprocess.run(["docker", "exec", "pia-worker-1", "piactl", "get", "regions"], capture_output=True, text=True)
all_regions = [r.strip() for r in res_regions.stdout.splitlines() if r.strip() and r.strip() != "auto"]
random.shuffle(all_regions)

# 2. Dong bo session hop le vao tat ca cac workers 13..20
for i in range(13, 21):
    print(f"Syncing session & connecting Worker {i:02d}...")
    subprocess.run(["docker", "exec", f"pia-worker-{i}", "sh", "-c", f"cat << 'EOF' > /opt/piavpn/etc/account.json\\n{valid_account_json}\\nEOF\\nchmod 600 /opt/piavpn/etc/account.json\\nchown root:piavpn /opt/piavpn/etc/account.json"], capture_output=True)
    subprocess.run(["docker", "exec", f"pia-worker-{i}", "pkill", "-HUP", "pia-daemon"], capture_output=True)
    time.sleep(0.5)
    
    target = all_regions[i % len(all_regions)]
    subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "background", "enable"], capture_output=True)
    subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "--timeout", "30", "set", "region", target], capture_output=True)
    subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "--timeout", "30", "connect"], capture_output=True)
    time.sleep(1)

time.sleep(5)
print("=== CHECK ALL 20 WORKERS FINAL STATUS ===")
online_count = 0
for i in range(1, 21):
    res_ip = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "vpnip"], capture_output=True, text=True)
    res_reg = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "region"], capture_output=True, text=True)
    res_st = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "connectionstate"], capture_output=True, text=True)
    res_hc = subprocess.run(["docker", "exec", f"pia-worker-{i}", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://127.0.0.1:9000/healthz"], capture_output=True, text=True)
    
    ip = res_ip.stdout.strip() or "Unknown"
    reg = res_reg.stdout.strip() or "Unknown"
    st = res_st.stdout.strip() or "Unknown"
    hc = res_hc.stdout.strip() or "ERR"
    
    is_on = (st == "Connected" and hc == "200")
    if is_on:
        online_count += 1
    icon = "🟢 ONLINE" if is_on else "🔴 OFFLINE"
    print(f"Worker {i:02d}: {icon:<9} | IP={ip:<16} | Region={reg:<24} | State={st:<12} | Healthz=HTTP {hc}")

print(f"\\nTong so Worker ONLINE: {online_count} / 20 Worker")
"""

import base64
b64 = base64.b64encode(script.encode()).decode()
child.sendline(f"echo '{b64}' | base64 -d > /tmp/sync_session_20.py && python3 /tmp/sync_session_20.py")
child.expect('Tong so Worker ONLINE:', timeout=180)
print(child.before)
child.expect('root@', timeout=30)
print(child.before)
child.close()
