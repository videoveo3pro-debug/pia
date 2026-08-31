import pexpect
import base64
import time

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=180, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

script = """
import subprocess, time, json

print("=== DEPLOYING OPTIMIZED WORKERS & TOKEN SYNC ===")
subprocess.run(["sh", "-c", "cd /root/pia && git pull origin main"])

# 1. Cap nhat proxy-entrypoint.sh va proxy-control-server.py vao toan bo 20 container
for i in range(1, 21):
    subprocess.run(["docker", "cp", "/root/pia/app/docker/proxy/proxy-entrypoint.sh", f"pia-worker-{i}:/usr/local/bin/proxy-entrypoint.sh"], capture_output=True)
    subprocess.run(["docker", "cp", "/root/pia/app/docker/proxy/proxy-control-server.py", f"pia-worker-{i}:/usr/local/bin/proxy-control-server.py"], capture_output=True)

# 2. Dam bao file token session slot 1 ton tai tren host
res_token = subprocess.run(["docker", "exec", "pia-worker-1", "cat", "/opt/piavpn/etc/account.json"], capture_output=True, text=True)
if res_token.stdout and '"loggedIn":true' in res_token.stdout:
    with open("/root/pia/prod/credentials/pia_session_slot_1.json", "w") as f:
        f.write(res_token.stdout)
    subprocess.run(["chmod", "600", "/root/pia/prod/credentials/pia_session_slot_1.json"])

# 3. Kiem tra va ket noi bat ky worker nao chua online
regions = [
    "us-california", "us-new-york", "us-chicago", "us-texas", "us-florida",
    "us-seattle", "us-atlanta", "us-denver", "us-virginia", "us-ohio",
    "ca-ontario", "ca-toronto", "ca-vancouver", "uk-london", "germany",
    "france", "netherlands", "sweden", "switzerland", "norway"
]

for i in range(1, 21):
    res_st = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "connectionstate"], capture_output=True, text=True)
    st = res_st.stdout.strip()
    if st != "Connected":
        target = regions[(i - 1) % len(regions)]
        print(f"Connecting Worker {i:02d} -> {target}...")
        subprocess.run(["docker", "exec", f"pia-worker-{i}", "sh", "-c", "cp /app/credentials/pia_session_slot_1.json /opt/piavpn/etc/account.json 2>/dev/null; chmod 600 /opt/piavpn/etc/account.json 2>/dev/null; chown root:piavpn /opt/piavpn/etc/account.json 2>/dev/null"], capture_output=True)
        subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "background", "enable"], capture_output=True)
        subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "--timeout", "30", "set", "region", target], capture_output=True)
        subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "--timeout", "30", "connect"], capture_output=True)
        time.sleep(1)

time.sleep(5)
print("=== FINAL 20 WORKERS LIVE IP STATUS ===")
online_ips = []
for i in range(1, 21):
    res_ip = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "vpnip"], capture_output=True, text=True)
    res_reg = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "region"], capture_output=True, text=True)
    res_st = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "connectionstate"], capture_output=True, text=True)
    res_hc = subprocess.run(["docker", "exec", f"pia-worker-{i}", "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://127.0.0.1:9000/healthz"], capture_output=True, text=True)
    
    ip = res_ip.stdout.strip() or "Unknown"
    reg = res_reg.stdout.strip() or "Unknown"
    st = res_st.stdout.strip() or "Unknown"
    hc = res_hc.stdout.strip() or "ERR"
    
    if st == "Connected" and hc == "200" and ip != "Unknown":
        online_ips.append(ip)
    
    print(f"Worker {i:02d}: IP={ip:<16} | Region={reg:<24} | Healthz=HTTP {hc} | State={st}")

print(f"\\nTong so Worker ONLINE & HEALTHY: {len(online_ips)} / 20")
print(f"Tong so IP DUY NHAT: {len(set(online_ips))} IP")
"""

b64 = base64.b64encode(script.encode()).decode()
child.sendline(f"echo '{b64}' | base64 -d > /tmp/deploy_all_perfect.py && python3 /tmp/deploy_all_perfect.py")
child.expect('Tong so IP DUY NHAT:', timeout=180)
print(child.before)
child.expect('root@', timeout=30)
print(child.before)
child.close()
