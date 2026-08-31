import pexpect
import base64

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=120, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

script = """
import subprocess, re, collections, json, urllib.request

print("=== THONG KE CHI TIET SO LUONG VA PHAN BO IP TREN HE THONG ===")

# 1. Lay danh sach 20 IP hien tai dang hoat dong tren 20 Worker
current_ips = {}
for i in range(1, 21):
    res = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "vpnip"], capture_output=True, text=True)
    res_st = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "connectionstate"], capture_output=True, text=True)
    res_reg = subprocess.run(["docker", "exec", f"pia-worker-{i}", "piactl", "get", "region"], capture_output=True, text=True)
    ip = res.stdout.strip() or "Unknown"
    st = res_st.stdout.strip() or "Unknown"
    reg = res_reg.stdout.strip() or "Unknown"
    current_ips[f"worker{i}"] = {"ip": ip, "state": st, "region": reg}

# 2. Trich xuat toan bo IP tu logs container backend
res_log = subprocess.run(["docker", "logs", "pia-socks5-api"], capture_output=True, text=True)
all_logs = res_log.stdout + res_log.stderr

# Regex tim tat ca cac mau IP
success_pattern = re.compile(r"Auto-rotate succeeded for (worker\d+):\s*([0-9.]+)\s*->\s*([0-9.]+)")
matches = success_pattern.findall(all_logs)

history_ips = collections.Counter()
subnets_24 = collections.Counter()
subnets_16 = collections.Counter()

for worker, old_ip, new_ip in matches:
    history_ips[old_ip] += 1
    history_ips[new_ip] += 1
    
for ip in history_ips.keys():
    parts = ip.split(".")
    if len(parts) == 4:
        subnets_24[f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"] += 1
        subnets_16[f"{parts[0]}.{parts[1]}.0.0/16"] += 1

for w, data in current_ips.items():
    if data["ip"] != "Unknown":
        history_ips[data["ip"]] += 1
        parts = data["ip"].split(".")
        if len(parts) == 4:
            subnets_24[f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"] += 1
            subnets_16[f"{parts[0]}.{parts[1]}.0.0/16"] += 1

total_unique_ips = len(history_ips)

print(f"\\n1. TONG QUAN SO LUONG IP:")
print(f"  - Tong so IP doc lap (Unique IPs) da cap phat: {total_unique_ips} IP")
print(f"  - So dai mang /24 (Subnets /24) khac nhau: {len(subnets_24)} dai")
print(f"  - So dai mang /16 (Class B Ranges) khac nhau: {len(subnets_16)} dai")
print(f"  - So IP dang online dong thoi (Active Now): {sum(1 for d in current_ips.values() if d['ip'] != 'Unknown')} / 20 IP")

print(f"\\n2. DANH SACH 20 IP HIEN TAI DANG HOAT DONG (LIVE WORKERS):")
for i in range(1, 21):
    w = f"worker{i}"
    info = current_ips.get(w, {})
    print(f"  - {w:<9}: IP: {info.get('ip', 'Unknown'):<16} | State: {info.get('state', ''):<12} | Region: {info.get('region', '')}")

print(f"\\n3. TOP 10 DAI MANG /24 XUAT HIEN NHIEU IP NHAT:")
for subnet, count in subnets_24.most_common(10):
    print(f"  - Subnet {subnet:<20}: {count:02d} dia chi IP doc lap")

print(f"\\n4. TOP 10 IP XUAT HIEN NHIEU LAN NHAT (POOL RECYCLING):")
for ip, count in history_ips.most_common(10):
    print(f"  - IP {ip:<16}: xuat hien {count:02d} lan")

print("\\n" + "="*70)
"""

b64 = base64.b64encode(script.encode()).decode()
child.sendline(f"echo '{b64}' | base64 -d > /tmp/stat_ips.py && python3 /tmp/stat_ips.py")
child.expect('=== THONG KE CHI TIET SO LUONG VA PHAN BO IP TREN HE THONG ===', timeout=45)
print(child.before)
child.expect('root@', timeout=60)
print(child.before)
child.close()
