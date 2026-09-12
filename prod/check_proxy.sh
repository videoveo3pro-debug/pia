''''exec python3 "$0" "$@" # '''
import json
import urllib.request
import subprocess
import sys
import time
import os

API_PORT = 8007
PROXY_PORT = 1087
PROXY_USER = "proxy_user"
PROXY_PASS = "proxy_password_secure123"

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("PROXY_PORT="):
                try: PROXY_PORT = int(line.split("=", 1)[1].strip())
                except: pass
            elif line.startswith("API_PORT="):
                try: API_PORT = int(line.split("=", 1)[1].strip())
                except: pass
            elif line.startswith("SOCKS5_USERNAME="):
                PROXY_USER = line.split("=", 1)[1].strip()
            elif line.startswith("SOCKS5_PASSWORD="):
                PROXY_PASS = line.split("=", 1)[1].strip()

print("=" * 75)
print("  KIEM TRA HE THONG PIA SOCKS5 PROXY POOL")
print("=" * 75)

print("\n[1/4] Kiem tra Backend API...")
try:
    with urllib.request.urlopen("http://127.0.0.1:{}/api/status".format(API_PORT), timeout=6) as resp:
        data = json.loads(resp.read().decode())
    print("  -> API Backend: HOAT DONG TOT (200 OK)")
except Exception as e:
    print("  -> API Backend LOI: {}".format(e))
    sys.exit(1)

nodes = data.get("nodes", [])
ready_nodes = [n for n in nodes if n.get("ready")]
unique_ips = set(n.get("current_ip") for n in ready_nodes if n.get("current_ip"))

print("\n[2/4] Danh sach Worker (Tong so: {}, READY: {})...".format(len(nodes), len(ready_nodes)))
print("-" * 75)
print("{:<10} {:<8} {:<18} {:<10} {:<10} {}".format('WORKER', 'READY', 'EXIT IP', 'UPTIME', 'ROTATIONS', 'COUNTRY'))
print("-" * 75)

over_70s_count = 0
for n in nodes:
    wid = n.get("id", "")
    ready = "YES" if n.get("ready") else "NO"
    ip = n.get("current_ip") or "N/A"
    uptime_sec = n.get("uptime_seconds")
    uptime_str = "{}s".format(uptime_sec) if uptime_sec is not None else "N/A"
    rot_cnt = n.get("rotation_count", 0)
    country = n.get("country") or n.get("country_hint") or ""
    
    if uptime_sec is not None and uptime_sec > 70:
        over_70s_count += 1
        uptime_str += " (!>70s)"
        
    print("{:<10} {:<8} {:<18} {:<10} {:<10} {}".format(wid, ready, ip, uptime_str, rot_cnt, country))

print("-" * 75)
print("Tong so Worker READY: {} / {}".format(len(ready_nodes), len(nodes)))
print("Tong so IP VPN doc lap (Unique IPs): {}".format(len(unique_ips)))
if len(unique_ips) >= 20:
    print("  => DAT YEU CAU: Cung cap tren 20 IP khac nhau!")
else:
    print("  => Dang ket noi them worker (Hien co {}/20+ IP)".format(len(unique_ips)))

if over_70s_count == 0:
    print("  => DAT YEU CAU: Khong co IP nao ton tai qua 70 giay!")
else:
    print("  => Thong tin: Co {} IP dang trong tien trinh xoay vi uptime > 70s".format(over_70s_count))

print("\n[3/4] Test 5 requests qua SOCKS5 Gateway (port {})...".format(PROXY_PORT))
proxy_ips = []
for r in range(1, 6):
    try:
        res = subprocess.run(
            ["curl", "-s", "-m", "8", "-x", "socks5h://{}:{}@127.0.0.1:{}".format(PROXY_USER, PROXY_PASS, PROXY_PORT), "https://api.ipify.org"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=10
        )
        out_ip = res.stdout.strip()
        if res.returncode == 0 and out_ip and "." in out_ip:
            proxy_ips.append(out_ip)
            print("  Request #{}: OK -> Exit IP: {}".format(r, out_ip))
        else:
            print("  Request #{}: Cho ket noi / Dang xoay IP".format(r))
    except Exception as exc:
        print("  Request #{}: Timeout ({})".format(r, exc))
    time.sleep(0.3)

print("So IP khac nhau thu duoc qua 5 requests: {}".format(len(set(proxy_ips))))

print("\n[4/4] Tai nguyen may chu:")
subprocess.run("uptime", shell=True)
subprocess.run("free -h", shell=True)
print("=" * 75)
