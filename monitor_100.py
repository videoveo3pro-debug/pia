import pexpect
import time

while True:
    child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=60, encoding='utf-8')
    child.expect('[pP]assword:')
    child.sendline('YFg8cWa54YTogkW9')
    child.expect('root@')
    
    child.sendline('tail -n 12 /tmp/run_100.log')
    child.expect('root@', timeout=30)
    out = child.before
    print("----- PROGRESS UPDATE -----")
    print(out)
    
    if "=== THONG KE KET QUA TEST 100 REQUESTS" in out:
        child.sendline('cat /tmp/run_100.log | grep -A 25 "=== THONG KE KET QUA TEST 100 REQUESTS"')
        child.expect('root@', timeout=30)
        print("===== FINAL REPORT =====")
        print(child.before)
        child.sendline('free -h && uptime')
        child.expect('root@', timeout=30)
        print(child.before)
        child.close()
        break
    
    child.close()
    time.sleep(30)
