import discord
from discord.ext import commands
import os
import asyncio
import logging
import struct
import opuslib

# ロギング設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = int(os.getenv('VOICE_CHANNEL_ID'))
PIPE_PATH = "/tmp/airplay-fifo"

# 音量ゲイン (1.0 = 原音, 2.0 = 2倍)
VOLUME_GAIN = 2.0

# Discord が要求するフレームサイズ
DISCORD_SAMPLE_RATE = 48000
DISCORD_CHANNELS = 2
DISCORD_FRAME_MS = 20
DISCORD_FRAME_SIZE = int(DISCORD_SAMPLE_RATE * DISCORD_CHANNELS * 2 * DISCORD_FRAME_MS / 1000)

# Shairport Sync 出力フォーマット
SHAIRPORT_SAMPLE_RATE = 44100
SHAIRPORT_CHANNELS = 2
SHAIRPORT_FRAME_SIZE = int(SHAIRPORT_SAMPLE_RATE * SHAIRPORT_CHANNELS * 2 * DISCORD_FRAME_MS / 1000)

# Opus エンコーダのビットレート (bps) - 高音質
OPUS_BITRATE = 510000

class RawOpusSource(discord.AudioSource):
    """
    パイプから生 PCM を読み込み、Opus に直接エンコードして送信する。
    """
    def __init__(self, pipe_file):
        # ブロックを避けるため、すでに開かれたファイルオブジェクトを受け取る
        self.pipe_file = pipe_file
        self._buffer = bytearray()
        self._encoder = opuslib.Encoder(DISCORD_SAMPLE_RATE, DISCORD_CHANNELS, opuslib.APPLICATION_AUDIO)
        self._encoder.bitrate = OPUS_BITRATE

    def _resample(self, data: bytes) -> bytes:
        ratio = DISCORD_SAMPLE_RATE / SHAIRPORT_SAMPLE_RATE
        in_samples = len(data) // 4
        out_samples = int(in_samples * ratio)
        in_frames = struct.unpack(f'<{in_samples * 2}h', data)
        out = []

        for i in range(out_samples):
            src = i / ratio
            idx = int(src)
            frac = src - idx

            if idx + 1 < in_samples:
                l = in_frames[idx * 2]     * (1 - frac) + in_frames[(idx + 1) * 2]     * frac
                r = in_frames[idx * 2 + 1] * (1 - frac) + in_frames[(idx + 1) * 2 + 1] * frac
            else:
                l = in_frames[idx * 2]
                r = in_frames[idx * 2 + 1]

            l = int(l * VOLUME_GAIN)
            r = int(r * VOLUME_GAIN)

            l = max(-32768, min(32767, l))
            r = max(-32768, min(32767, r))
            out.extend([l, r])

        return struct.pack(f'<{len(out)}h', *out)

    def read(self) -> bytes:
        if self.pipe_file is None:
            return b''

        try:
            while len(self._buffer) < SHAIRPORT_FRAME_SIZE:
                chunk = self.pipe_file.read(SHAIRPORT_FRAME_SIZE - len(self._buffer))
                if not chunk:
                    # 曲が終了した（書き込み側が閉じた）場合は b'' を返して再生を終了させる
                    return b''
                self._buffer.extend(chunk)

            raw = bytes(self._buffer[:SHAIRPORT_FRAME_SIZE])
            self._buffer = self._buffer[SHAIRPORT_FRAME_SIZE:]

            resampled = self._resample(raw)
            samples_per_channel = DISCORD_FRAME_SIZE // (DISCORD_CHANNELS * 2)
            return self._encoder.encode(resampled, samples_per_channel)

        except Exception as e:
            logger.error(f"❌ Error reading from pipe: {e}")
            return b''

    def is_opus(self) -> bool:
        return True

    def close(self):
        if self.pipe_file:
            try:
                self.pipe_file.close()
            except Exception as e:
                logger.error(f"Error closing pipe: {e}")
            finally:
                self.pipe_file = None
                logger.info("✅ Pipe closed")


class AirPlayBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.vc = None

    async def setup_hook(self):
        logger.info("Bot setup_hook called")
        self.loop.create_task(self.ensure_voice_connection())

    async def on_ready(self):
        logger.info(f'✅ Logged in as {self.user}')

    async def ensure_voice_connection(self):
        await self.wait_until_ready()

        while True:
            try:
                channel = self.get_channel(CHANNEL_ID)
                if channel is None:
                    logger.error(f"❌ Channel ID {CHANNEL_ID} not found!")
                    await asyncio.sleep(5)
                    continue

                if self.vc is None or not self.vc.is_connected():
                    logger.info(f"Connecting to voice channel: {channel.name}")
                    self.vc = await channel.connect()
                    logger.info("✅ Connected to voice channel")
                    self.loop.create_task(self.stream_airplay())
                    break
            except Exception as e:
                logger.error(f"❌ Error connecting to voice: {e}")
                await asyncio.sleep(5)

    async def stream_airplay(self):
        while not os.path.exists(PIPE_PATH):
            logger.info("⏳ Waiting for pipe file to be created...")
            await asyncio.sleep(2)

        logger.info("✅ Pipe file exists!")

        while True:
            try:
                if self.vc and not self.vc.is_playing():
                    def open_pipe():
                        # ここでパイプを開く。AirPlayが開始されるまでスレッドは待機する
                        return open(PIPE_PATH, 'rb', buffering=0)

                    logger.info("🎵 Waiting for incoming AirPlay audio... (Ready to play)")
                    
                    # メインループをブロックしないよう別スレッドで待機
                    pipe_file = await asyncio.to_thread(open_pipe)
                    
                    logger.info("▶️ AirPlay playback started!")
                    source = RawOpusSource(pipe_file)
                    
                    self.vc.play(
                        source,
                        after=lambda e: logger.error(f'❌ Player error: {e}') if e else logger.info("⏹️ AirPlay playback stopped.")
                    )
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"❌ Error in stream_airplay: {e}")
                await asyncio.sleep(2)

if __name__ == "__main__":
    bot = AirPlayBot()
    bot.run(TOKEN)