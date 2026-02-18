# AirPlay to Discord Bridge

Mac/iPhone/iPad の AirPlay から Shairport Sync 経由で Discord ボイスチャネルに音声をストリーミングするシステム。

## 前提条件

- Kubernetes クラスタ（k3s など）
- kubectl がセットアップ済み
- Docker（イメージビルド用）
- Tailscale（iPhone/iPad からのアクセス時）

## クイックスタート

### 1. リポジトリをクローン

```bash
git clone <repository-url>
cd airplay-discord-bot
```

### 2. 環境変数を設定

```bash
export DISCORD_TOKEN=your_bot_token_here
export VOICE_CHANNEL_ID=your_channel_id_here
```

### 3. デプロイを実行

```bash
chmod +x start.sh
./start.sh
```

## 設定

### Discord Bot トークン取得

1. [Discord Developer Portal](https://discord.com/developers/applications) にアクセス
2. 新しいアプリケーションを作成
3. Bot を追加
4. トークンをコピー → `DISCORD_TOKEN` に設定

### ボイスチャネル ID 取得

1. Discord で対象サーバーのテキストチャネルを右クリック
2. 「チャネル ID をコピー」
3. 値を `VOICE_CHANNEL_ID` に設定

## AirPlay デバイスからの接続

### Mac から
- メニューバーの音量アイコン → 「出力先」で「Discord AirPlay」を選択

### iPhone/iPad から（Tailscale 経由）
1. Tailscale に参加していることを確認
2. コントロールセンター → 「今聴いている項目」 → AirPlay アイコン
3. 「Discord AirPlay」を選択

## トラブルシューティング

### AirPlay デバイスが見つからない場合

```bash
# Tailscale の mDNS を確認
dns-sd -B _raop._tcp local.

# Kubernetes ポッドのステータスを確認
kubectl get pods -n airplay
kubectl logs -f deployment/discord-bot -n airplay
```

### ボイスチャネル接続エラー

```bash
# ボット権限を確認
# - ボイスチャネルへの接続権限
# - 音声送信権限
```

## ファイル構成

```
.
├── bot/                          # Discord Bot コード
│   ├── Dockerfile
│   ├── main.py
│   └── requirements.txt
├── shairport-sync/               # Shairport Sync 設定
│   └── shairport-sync.conf
├── k8s/                          # Kubernetes マニフェスト
│   ├── namespace.yaml
│   ├── shairport-configmap.yaml
│   ├── discord-configmap.yaml
│   ├── shairport-deployment.yaml
│   └── discord-deployment.yaml
├── start.sh                      # デプロイスクリプト
├── docker-compose.yml            # Docker Compose（参考用）
└── README.md
```

## 技術詳細

- **Shairport Sync**: Classic AirPlay (AirPlay 1) 受信
- **FIFO パイプ**: `/tmp/airplay-fifo` で Shairport Sync と Discord Bot が音声データを共有
- **Opus エンコード**: 高音質（510kbps）でエンコード
- **Kubernetes**: `hostNetwork: true` で Tailscale NIC に直接バインド

## ライセンス

MIT

## 作成者

Claude Opus 4.6
