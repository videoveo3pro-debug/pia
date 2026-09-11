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
    with urllib.request.urlopen(f"http://127.0.0.1:{API_PORT}/api/status", timeout=6) as resp:
        data = json.loads(resp.read().decode())
    print("  -> API Backend: HOAT DONG TOT (200 OK)")
except Exception as e:
    print(f"  -> API Backend LOI: {e}")
    sys.exit(1)

nodes = data.get("nodes", [])
ready_nodes = [n for n in nodes if n.get("ready")]
unique_ips = set(n.get("current_ip") for n in ready_nodes if n.get("current_ip"))

print(f"\n[2/4] Danh sach Worker (Tong so: {len(nodes)}, READY: {len(ready_nodes)})...")
print("-" * 75)
print(f"{'WORKER':<10} {'READY':<8} {'EXIT IP':<18} {'UPTIME':<10} {'ROTATIONS':<10} {'COUNTRY'}")
print("-" * 75)

over_70s_count = 0
for n in nodes:
    wid = n.get("id", "")
    ready = "YES" if n.get("ready") else "NO"
    ip = n.get("current_ip") or "N/A"
    uptime_sec = n.get("uptime_seconds")
    uptime_str = f"{uptime_sec}s" if uptime_sec is not None else "N/A"
    rot_cnt = n.get("rotation_count", 0)
    country = n.get("country") or n.get("country_hint") or ""
    
    if uptime_sec is not None and uptime_sec > 70:
        over_70s_count += 1
        uptime_str += " (!>70s)"
        
    print(f"{wid:<10} {ready:<8} {ip:<18} {uptime_str:<10} {rot_cnt:<10} {country}")

print("-" * 75)
print(f"Tong so Worker READY: {len(ready_nodes)} / {len(nodes)}")
print(f"Tong so IP VPN doc lap (Unique IPs): {len(unique_ips)}")
if len(unique_ips) >= 20:
    print("  => DAT YEU CAU: Cung cap tren 20 IP khac nhau!")
else:
    print(f"  => Dang ket noi them worker (Hien co {len(unique_ips)}/20+ IP)")

if over_70s_count == 0:
    print("  => DAT YEU CAU: Khong co IP nao ton tai qua 70 giay!")
else:
    print(f"  => Thong tin: Co {over_70s_count} IP dang trong tien trinh xoay vi uptime > 70s")

print(f"\n[3/4] Test 5 requests qua SOCKS5 Gateway (port {PROXY_PORT})...")
proxy_ips = []
for r in range(1, 6):
    try:
        res = subprocess.run(
            ["curl", "-s", "-m", "8", "-x", f"socks5h://{PROXY_USER}:{PROXY_PASS}@127.0.0.1:{PROXY_PORT}", "https://api.ipify.org"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=10
        )
        out_ip = res.stdout.strip()
        if res.returncode == 0 and out_ip and "." in out_ip:
            proxy_ips.append(out_ip)
            print(f"  Request #{r}: OK -> Exit IP: {out_ip}")
        else:
            print(f"  Request #{r}: Cho ket noi / Dang xoay IP")
    except Exception as exc:
        print(f"  Request #{r}: Timeout ({exc})")
    time.sleep(0.3)

print(f"So IP khac nhau thu duoc qua 5 requests: {len(set(proxy_ips))}")

print("\n[4/4] Tai nguyen may chu:")
subprocess.run("uptime", shell=True)
subprocess.run("free -h", shell=True)
print("=" * 75)
