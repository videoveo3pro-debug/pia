import pexpect
import base64

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=60, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

parser_py = """
import subprocess, re, collections, datetime

print("=== PHAN TICH TOAN BO LOGS AUTO-ROTATE TREN SERVER ===")

# 1. Doc toan bo logs tu container backend API
res = subprocess.run(["docker", "logs", "pia-socks5-api"], capture_output=True, text=True)
all_logs = res.stdout + res.stderr

# Tim cac dong log rotate thanh cong va that bai
# Format: Auto-rotate succeeded for workerX: old_ip -> new_ip
success_pattern = re.compile(r"Auto-rotate succeeded for (worker\d+):\s*([0-9.]+)\s*->\s*([0-9.]+)")
failed_pattern = re.compile(r"Auto-rotate failed for (worker\d+):\s*(.*)")

success_events = success_pattern.findall(all_logs)
failed_events = failed_pattern.findall(all_logs)

# Thong ke theo Worker
worker_rotates = collections.defaultdict(list)
unique_ips = set()
transitions = []

for worker, old_ip, new_ip in success_events:
    worker_rotates[worker].append((old_ip, new_ip))
    unique_ips.add(old_ip)
    unique_ips.add(new_ip)
    transitions.append(f"{old_ip} -> {new_ip}")

print(f"Tong so luot xoay IP thanh cong (Auto-rotate succeeded): {len(success_events)}")
print(f"Tong so luot retry/failed (Auto-rotate failed): {len(failed_events)}")
print(f"Tong so luot IP doc lap da xuat hien qua cac lan rotate: {len(unique_ips)}")
print(f"So worker da tham gia rotate: {len(worker_rotates)}")

print("\\n--- THONG KE SO LAN XOAY IP TREN TUNG WORKER ---")
for i in range(1, 21):
    w_name = f"worker{i}"
    events = worker_rotates.get(w_name, [])
    print(f"  - {w_name:<9}: {len(events):02d} lan xoay IP")

print("\\n--- TOP 15 LAN CHUYEN DOI IP GAN NHAT (RECENT TRANSITIONS) ---")
for idx, (worker, old_ip, new_ip) in enumerate(success_events[-15:], 1):
    print(f"  {idx:02d}. [{worker:<8}] {old_ip:<15}  ==>  {new_ip:<15}")

# Kiem tra dung luong log luu tren he thong
print("\\n--- THONG TIN LUU TRU LOGS TREN SERVER ---")
res_docker_log = subprocess.run(["sh", "-c", "docker inspect --format='{{.LogPath}}' pia-socks5-api 2>/dev/null"], capture_output=True, text=True)
log_path = res_docker_log.stdout.strip()
if log_path:
    res_size = subprocess.run(["ls", "-lh", log_path], capture_output=True, text=True)
    print(f"File log Docker backend: {log_path}")
    print(f"Dung luong hien tai: {res_size.stdout.strip().split()[4] if res_size.stdout else 'N/A'}")
"""

b64 = base64.b64encode(parser_py.encode()).decode()
child.sendline(f"echo '{b64}' | base64 -d > /tmp/parse_rotates.py && python3 /tmp/parse_rotates.py")
child.expect('=== PHAN TICH TOAN BO LOGS AUTO-ROTATE TREN SERVER ===', timeout=45)
print(child.before)
child.expect('root@', timeout=30)
print(child.before)
child.close()
