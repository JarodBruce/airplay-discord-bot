#!/bin/bash
set -e

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