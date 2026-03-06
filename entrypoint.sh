#!/bin/bash
set -e

# Start D-Bus and Avahi daemon for mDNS
echo "Starting D-Bus and Avahi daemon..."
mkdir -p /run/dbus /var/run/dbus

if [ -f /run/dbus/pid ]; then
  dbus_pid="$(cat /run/dbus/pid 2>/dev/null || true)"
  if [ -z "$dbus_pid" ] || ! kill -0 "$dbus_pid" 2>/dev/null; then
    rm -f /run/dbus/pid
  fi
fi

if ! pgrep -x dbus-daemon >/dev/null 2>&1; then
  dbus-daemon --system --fork
fi

if ! pgrep -x avahi-daemon >/dev/null 2>&1; then
  avahi-daemon -D
fi

# Create the named pipe for audio data
echo "Creating named pipe at /tmp/airplay-fifo..."
rm -f /tmp/airplay-fifo
mkfifo /tmp/airplay-fifo

# Start shairport-sync in the background
echo "Starting shairport-sync..."
shairport-sync -c /etc/shairport-sync.conf -a "Discord AirPlay" &

# Start the Python bot in the foreground
echo "Starting discord bot..."
exec python main.py
