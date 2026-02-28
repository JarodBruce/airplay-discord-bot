FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    shairport-sync \
    avahi-daemon \
    dbus \
    ffmpeg \
    build-essential \
    libopus-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install python dependencies first to leverage Docker cache
COPY bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy config and entrypoint
COPY shairport-sync/shairport-sync.conf /etc/shairport-sync.conf
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Copy bot source code
COPY bot/ .

ENTRYPOINT ["/app/entrypoint.sh"]