import pexpect
import base64
import time

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=60, encoding='utf-8')
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

# Launch nohup in background
child.sendline("nohup python3 /tmp/run_100.py > /tmp/run_100.log 2>&1 &")
child.expect('root@', timeout=30)
print("Started nohup background test on VPS.")
child.close()
