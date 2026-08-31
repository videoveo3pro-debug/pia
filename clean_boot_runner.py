import pexpect

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=120, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

script = """
import subprocess, time

# 1. Luu token hop le vao session file chia se
res = subprocess.run(["docker", "exec", "pia-worker-1", "cat", "/opt/piavpn/etc/account.json"], capture_output=True, text=True)
if res.stdout and '"loggedIn":true' in res.stdout:
    with open("/root/pia/prod/credentials/pia_session_slot_1.json", "w") as f:
        f.write(res.stdout)
    subprocess.run(["chmod", "600", "/root/pia/prod/credentials/pia_session_slot_1.json"])
    print("Saved valid session token to pia_session_slot_1.json")

# 2. Restart worker 13..20 so they cleanly boot with the valid session token
print("Restarting workers 13..20...")
for i in range(13, 21):
    subprocess.run(["docker", "restart", f"pia-worker-{i}"], capture_output=True)
    time.sleep(0.5)

print("Waiting 10s for workers to initialize...")
time.sleep(10)

# 3. Fast status check
print("=== FINAL 20 WORKERS STATUS CHECK ===")
online_count = 0
for i in range(1, 21):
    try:
        r_st = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "connectionstate"], capture_output=True, text=True, timeout=3)
        st = r_st.stdout.strip() or "Unknown"
    except Exception:
        st = "Timeout"
    
    try:
        r_ip = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "vpnip"], capture_output=True, text=True, timeout=3)
        ip = r_ip.stdout.strip() or "Unknown"
    except Exception:
        ip = "Unknown"

    try:
        r_reg = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "region"], capture_output=True, text=True, timeout=3)
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
child.sendline(f"echo '{b64}' | base64 -d > /tmp/clean_boot_13_20.py && python3 /tmp/clean_boot_13_20.py")
child.expect('Tong so Worker ONLINE:', timeout=120)
print(child.before)
child.expect('root@', timeout=30)
print(child.before)
child.close()
