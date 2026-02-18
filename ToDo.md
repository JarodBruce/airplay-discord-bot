コーディングエージェント（Cursor, GitHub Copilot, Cline等）にそのまま渡して開発を進められるよう、**システム構成図、ディレクトリ構造、各種設定ファイル、ボットのソースコード**を整理しました。

このプロジェクトは、**Shairport Sync (AirPlay受信)** と **Discord Bot (音声転送)** を同じDocker環境で動かし、Linuxの**FIFO（名前付きパイプ）**を介して音声を渡す構成です。

---

# Project: AirPlay to Discord Bridge Bot

## 1. システム構成

1. **Shairport Sync (Container A):** iPhone等からAirPlayを受信し、音声をRAWデータとして `/tmp/airplay-fifo` に書き出す。
2. **Discord Bot (Container B):** パイプ `/tmp/airplay-fifo` を監視し、FFmpegを使用してDiscordのボイスチャンネルへストリーミングする。
3. **Shared Volume:** 2つのコンテナ間でパイプファイルを共有。

## 2. ディレクトリ構造

```text
airplay-discord-bot/
├── docker-compose.yml
├── shairport-sync/
│   └── shairport-sync.conf
└── bot/
    ├── Dockerfile
    ├── requirements.txt
    └── main.py

```

## 3. 各設定ファイルの定義

### ① `docker-compose.yml`

AirPlayの検知（mDNS/Bonjour）のため、`network_mode: host` が必須です。

```yaml
services:
  shairport-sync:
    image: mikebrady/shairport-sync:latest
    container_name: airplay-receiver
    network_mode: host
    volumes:
      - ./shairport-sync/shairport-sync.conf:/etc/shairport-sync.conf
      - pipe-data:/tmp
    restart: always

  discord-bot:
    build: ./bot
    container_name: discord-audio-bot
    network_mode: host
    depends_on:
      - shairport-sync
    volumes:
      - pipe-data:/tmp
    environment:
      - DISCORD_TOKEN=YOUR_BOT_TOKEN_HERE
      - VOICE_CHANNEL_ID=YOUR_VOICE_CHANNEL_ID_HERE
    restart: always

volumes:
  pipe-data:

```

### ② `shairport-sync/shairport-sync.conf`

出力を「パイプ」に設定します。

```conf
general = {
  name = "Discord AirPlay";
  output_backend = "pipe";
};

sessioncontrol = {
  wait_for_completion = "no";
};

pipe = {
  name = "/tmp/airplay-fifo";
};

```

### ③ `bot/requirements.txt`

```text
discord.py[voice]
PyNaCl
python-dotenv

```

### ④ `bot/Dockerfile`

音声処理のために `ffmpeg` をインストールしたPython環境を作成します。

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]

```

### ⑤ `bot/main.py`

パイプから入力を受け取り、Discordへ流すメインロジックです。

```python
import discord
from discord.ext import commands
import os
import asyncio

TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = int(os.getenv('VOICE_CHANNEL_ID'))
PIPE_PATH = "/tmp/airplay-fifo"

class AirPlayBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def on_ready(self):
        print(f'Logged in as {self.user}')
        channel = self.get_channel(CHANNEL_ID)
        if channel:
            vc = await channel.connect()
            self.loop.create_task(self.stream_airplay(vc))

    async def stream_airplay(self, vc):
        # パイプが存在するまで待機
        while not os.path.exists(PIPE_PATH):
            print("Waiting for pipe...")
            await asyncio.sleep(2)

        print("Starting stream from pipe...")
        
        # FFmpegの設定: 
        # shairport-syncはデフォルトで 44100Hz, 16bit, Stereo で出力する
        ffmpeg_options = {
            'options': '-f s16le -ar 44100 -ac 2',
            'before_options': '-re'
        }

        while True:
            if not vc.is_playing():
                source = discord.FFmpegPCMAudio(PIPE_PATH, **ffmpeg_options)
                vc.play(source, after=lambda e: print(f'Player error: {e}') if e else None)
            await asyncio.sleep(1)

bot = AirPlayBot()
bot.run(TOKEN)

```

---

## 4. 構築と実行のステップ

1. **Discord Developer Portal** でボットを作成し、トークンを取得してください。
* `GUILD_VOICE_STATES` などのインテントを有効にする必要があります。


2. `docker-compose.yml` 内の `DISCORD_TOKEN` と `VOICE_CHANNEL_ID` を書き換えてください。
3. 以下のコマンドで起動します。
```bash
docker-compose up --build -d

```


4. iPhoneのコントロールセンターを開き、音楽の出力先から **"Discord AirPlay"** を選択します。
5. ボットが自動的にボイスチャンネルに参加し、音楽が流れ始めます。

---

## 5. エージェントへの指示出しヒント

コーディングエージェントに投げる際は、以下のように伝えるとスムーズです。

> 「AirPlayをShairport Syncで受信し、名前付きパイプを経由してDiscord.pyでボイスチャットに流すツールを作りたい。提供したコードをベースに、パイプの作成（`mkfifo`）がDocker起動時に自動で行われるようにし、音声が途切れた際の再接続ロジックを強化してほしい。」

この構成で不明な点や、追加したい機能（再生中の曲名表示など）はありますか？
