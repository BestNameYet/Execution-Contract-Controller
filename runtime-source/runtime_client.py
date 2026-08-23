#!/usr/bin/env python3
import json
import socket
import sys
from pathlib import Path

MANIFEST = Path('/mnt/data/execution_runtime/runtime_manifest.json')

def call(op, **kwargs):
    m = json.loads(MANIFEST.read_text())
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(m['endpoint'])
    s.sendall((json.dumps({'op': op, **kwargs}, ensure_ascii=False, separators=(',', ':')) + '\n').encode())
    b = b''
    while b'\n' not in b:
        c = s.recv(65536)
        if not c:
            break
        b += c
    s.close()
    return json.loads(b.split(b'\n', 1)[0])

def main():
    if len(sys.argv) < 2:
        raise SystemExit('usage: runtime_client.py OP [JSON_OBJECT]')
    kwargs = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    if not isinstance(kwargs, dict):
        raise SystemExit('JSON_OBJECT must decode to an object')
    print(json.dumps(call(sys.argv[1], **kwargs), ensure_ascii=False, separators=(',', ':')))

if __name__ == '__main__':
    main()
