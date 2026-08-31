import pexpect
import time
import sys

while True:
    child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=60, encoding='utf-8')
    child.expect('[pP]assword:')
    child.sendline('YFg8cWa54YTogkW9')
    child.expect('root@')
    
    child.sendline('tail -n 8 /tmp/stress_1000.log')
    child.expect('root@', timeout=30)
    out = child.before
    print("----- STRESS TEST PROGRESS -----")
    print(out)
    
    if "=== THONG KE KET QUA STRESS-TEST 1000 REQUESTS" in out:
        child.sendline('cat /tmp/stress_1000.log | grep -A 40 "=== THONG KE KET QUA STRESS-TEST 1000 REQUESTS"')
        child.expect('root@', timeout=30)
        print("===== FINAL STRESS TEST REPORT =====")
        print(child.before)
        child.sendline('free -h && uptime')
        child.expect('root@', timeout=30)
        print(child.before)
        child.close()
        break
    
    child.close()
    time.sleep(12)
