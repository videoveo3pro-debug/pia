import pexpect

child = pexpect.spawn('ssh -o StrictHostKeyChecking=no root@103.82.193.113', timeout=240)
child.expect('[pP]assword:')
child.sendline('YFg8cWa54YTogkW9')
child.expect('root@')

child.sendline('python3 /tmp/bench.py; echo "=== RESOURCE USAGE ==="; free -h; uptime')
child.expect('root@', timeout=240)
print(child.before.decode())
child.close()
