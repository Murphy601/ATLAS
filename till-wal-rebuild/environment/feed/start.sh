#!/bin/sh
# Harbor replaces CMD with `sleep infinity` but keeps this ENTRYPOINT.
python3 /opt/nyota-feed/serve.py >/tmp/nyota-feed.log 2>&1 &
i=0
while [ "$i" -lt 50 ]; do
  python3 -c "import socket; s=socket.create_connection(('127.0.0.1',9377),0.2); s.close()" 2>/dev/null && break
  i=$((i + 1))
  sleep 0.1
done
exec "$@"
