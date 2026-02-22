import asyncio
import logging
import os
import struct

import discord
import opuslib
from discord.ext import commands

# ==============================================================================
# Configuration & Constants
# ==============================================================================

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# Environment Variables
TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = int(os.getenv('VOICE_CHANNEL_ID', '0'))
PIPE_PATH = "/tmp/airplay-fifo"

# Audio Settings
VOLUME_GAIN = 2.0  # 1.0 = 原音, 2.0 = 2倍の音量

# Discord Audio Configuration (Required by Discord)
DISCORD_SAMPLE_RATE = 48000
DISCORD_CHANNELS = 2
DISCORD_FRAME_MS = 20
DISCORD_FRAME_SIZE = int(DISCORD_SAMPLE_RATE * DISCORD_CHANNELS * 2 * DISCORD_FRAME_MS / 1000)

# Shairport Sync Audio Configuration (Input from pipe)
SHAIRPORT_SAMPLE_RATE = 44100
SHAIRPORT_CHANNELS = 2
SHAIRPORT_FRAME_SIZE = int(SHAIRPORT_SAMPLE_RATE * SHAIRPORT_CHANNELS * 2 * DISCORD_FRAME_MS / 1000)

# Opus Encoder Settings (bps)
OPUS_BITRATE = 510000

# ==============================================================================
# Audio Source Component
# ==============================================================================

class RawOpusSource(discord.AudioSource):
    """
    パイプから生PCMデータを読み込み、リサンプリングと音量調整を行い、
    OpusフォーマットにエンコードしてDiscordに送信するオーディオソース。
    """
    def __init__(self, pipe_file):
        # ブロックを避けるため、すでに開かれたファイルオブジェクトを受け取る
        self.pipe_file = pipe_file
        self._buffer = bytearray()
        
        # 音声エンコーダの初期化
        self._encoder = opuslib.Encoder(DISCORD_SAMPLE_RATE, DISCORD_CHANNELS, opuslib.APPLICATION_AUDIO)
        self._encoder.bitrate = OPUS_BITRATE

    def _resample_and_adjust_volume(self, data: bytes) -> bytes:
        """
        44.1kHz から 48kHz への簡易線形補間リサンプリングと音量調整を行う。
        """
        ratio = DISCORD_SAMPLE_RATE / SHAIRPORT_SAMPLE_RATE
        in_samples = len(data) // 4  # 16-bit stereo = 4 bytes per sample
        out_samples = int(in_samples * ratio)
        
        # 音声データを16bit整数(=h)の配列として展開
        in_frames = struct.unpack(f'<{in_samples * 2}h', data)
        out = []

        for i in range(out_samples):
            src = i / ratio
            idx = int(src)
            frac = src - idx

            # 線形補間
            if idx + 1 < in_samples:
                l_orig = in_frames[idx * 2] * (1 - frac) + in_frames[(idx + 1) * 2] * frac
                r_orig = in_frames[idx * 2 + 1] * (1 - frac) + in_frames[(idx + 1) * 2 + 1] * frac
            else:
                l_orig = in_frames[idx * 2]
                r_orig = in_frames[idx * 2 + 1]

            # 音量調整
            l_adj = int(l_orig * VOLUME_GAIN)
            r_adj = int(r_orig * VOLUME_GAIN)

            # クリッピング防止 (16-bit 範囲に収める)
            out.append(max(-32768, min(32767, l_adj)))
            out.append(max(-32768, min(32767, r_adj)))

        return struct.pack(f'<{len(out)}h', *out)

    def read(self) -> bytes:
        """
        Discord 側に音声を供給するために繰り返し呼ばれる関数。
        1フレーム分のOpusエンコード済みデータを返す。
        """
        if self.pipe_file is None:
            return b''

        try:
            # 必要なフレームサイズ分だけパイプから読み込む
            while len(self._buffer) < SHAIRPORT_FRAME_SIZE:
                chunk = self.pipe_file.read(SHAIRPORT_FRAME_SIZE - len(self._buffer))
                if not chunk:
                    # 曲が終了した（書き込み側がパイプを閉じた）場合
                    return b''
                self._buffer.extend(chunk)

            # バッファから1フレーム分を取り出す
            raw = bytes(self._buffer[:SHAIRPORT_FRAME_SIZE])
            self._buffer = self._buffer[SHAIRPORT_FRAME_SIZE:]

            # 変換処理 (リサンプル + 音量調整)
            resampled = self._resample_and_adjust_volume(raw)
            
            # チャンネルごとのサンプル数を計算してエンコード
            samples_per_channel = DISCORD_FRAME_SIZE // (DISCORD_CHANNELS * 2)
            return self._encoder.encode(resampled, samples_per_channel)

        except Exception as e:
            logger.error(f"❌ Error reading/encoding audio from pipe: {e}")
            return b''

    def is_opus(self) -> bool:
        return True

    def close(self):
        """再生終了時に呼ばれ、パイプを安全に閉じる"""
        if self.pipe_file:
            try:
                self.pipe_file.close()
            except Exception as e:
                logger.error(f"Error closing pipe: {e}")
            finally:
                self.pipe_file = None
                logger.info("✅ Pipe closed")


# ==============================================================================
# Discord Bot
# ==============================================================================

class AirPlayBot(commands.Bot):
    """
    指定されたボイスチャンネルに接続し、AirPlayのストリームを再生するボット。
    """
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.vc = None

    async def setup_hook(self):
        logger.info("Bot setup_hook called. Starting background tasks.")
        # Pipe監視タスクを開始
        self.loop.create_task(self.stream_airplay())

    async def on_ready(self):
        logger.info(f'✅ Logged in as {self.user}')

    def get_human_count(self) -> int:
        """指定されたボイスチャンネル内の人間（Bot以外）の数を取得する"""
        channel = self.get_channel(CHANNEL_ID)
        if not channel or not isinstance(channel, discord.VoiceChannel):
            return 0
        return len([m for m in channel.members if not m.bot])

    async def check_and_join(self) -> bool:
        """条件（人間がいる）を満たしている場合にボイスチャンネルに参加する"""
        if not CHANNEL_ID:
            logger.error("❌ VOICE_CHANNEL_ID is not set or invalid!")
            return False

        channel = self.get_channel(CHANNEL_ID)
        if channel is None:
            logger.warning(f"⚠️ Channel {CHANNEL_ID} not found.")
            return False

        if self.get_human_count() > 0:
            if self.vc is None or not self.vc.is_connected():
                logger.info(f"Connecting to voice channel: {channel.name} (with self_deaf=True)")
                # スピーカーミュート（self_deaf=True）の状態でジョイン
                self.vc = await channel.connect(self_deaf=True)
                logger.info("✅ Connected to voice channel (Deafened)")
            return True
        else:
            logger.info(f"Empty voice channel. Waiting for humans to join...")
            return False

    async def stream_airplay(self):
        """パイプを監視し、データが流れてきたら条件を確認して再生を開始するタスク"""
        await self.wait_until_ready()

        while not os.path.exists(PIPE_PATH):
            logger.info("⏳ Waiting for pipe file to be created...")
            await asyncio.sleep(2)

        logger.info("✅ Pipe file exists! Ready to monitor AirPlay.")

        while True:
            try:
                # 1. パイプがオープンされる（AirPlay接続）のを待つ
                def open_pipe():
                    return open(PIPE_PATH, 'rb', buffering=0)

                logger.info("🎵 Waiting for incoming AirPlay audio...")
                pipe_file = await asyncio.to_thread(open_pipe)
                
                # 最初の手がかりとして1フレーム分読み込んでみる（接続確認）
                # これにより、単なる接続ではなくデータが流れ始めたことを確認する
                first_chunk = await asyncio.to_thread(pipe_file.read, SHAIRPORT_FRAME_SIZE)
                if not first_chunk:
                    logger.info("Empty stream detected. Closing.")
                    pipe_file.close()
                    continue

                logger.info("▶️ AirPlay connection detected and data received!")

                # 2. 人間がいるか確認し、いればジョインする
                connected = await self.check_and_join()
                
                if connected:
                    logger.info("▶️ Starting playback!")
                    source = RawOpusSource(pipe_file)
                    # 最初の一歩をバッファに詰める
                    source._buffer.extend(first_chunk)
                    
                    def after_playback(error):
                        if error:
                            logger.error(f'❌ Player error: {error}')
                        else:
                            logger.info("⏹️ AirPlay playback stopped.")
                            
                    self.vc.play(source, after=after_playback)

                    # 再生中、人間がいなくなったら切断する監視ループ
                    while self.vc and self.vc.is_playing():
                        if self.get_human_count() == 0:
                            logger.info("Empty channel detected. Stopping playback and leaving.")
                            self.vc.stop()
                            await self.vc.disconnect()
                            self.vc = None
                            break
                        await asyncio.sleep(5)
                    
                    # 再生が終了（人間がいなくなった場合を含む）したら切断
                    if self.vc and self.vc.is_connected():
                        await self.vc.disconnect()
                        self.vc = None
                        logger.info("✅ Disconnected from voice channel.")
                else:
                    # 人間がいない場合はパイプを閉じて次の接続を待つ
                    logger.info("No humans in channel. Closing AirPlay stream.")
                    pipe_file.close()

            except Exception as e:
                logger.error(f"❌ Error in stream_airplay loop: {e}")
                if self.vc and self.vc.is_connected():
                    await self.vc.disconnect()
                    self.vc = None
                
            await asyncio.sleep(1)


# ==============================================================================
# Main Entry Point
# ==============================================================================

if __name__ == "__main__":
    if not TOKEN:
        logger.error("❌ DISCORD_TOKEN is not set in environment!")
    else:
        bot = AirPlayBot()
        bot.run(TOKEN)