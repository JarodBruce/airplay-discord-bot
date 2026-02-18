#!/bin/bash

set -e

# カラー定義
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}AirPlay to Discord Bridge - Kubernetes${NC}"
echo -e "${GREEN}========================================${NC}"

# 環境変数チェック
if [ -z "$DISCORD_TOKEN" ]; then
    echo -e "${RED}❌ Error: DISCORD_TOKEN is not set${NC}"
    echo "Please set: export DISCORD_TOKEN=your_token_here"
    exit 1
fi

if [ -z "$VOICE_CHANNEL_ID" ]; then
    echo -e "${RED}❌ Error: VOICE_CHANNEL_ID is not set${NC}"
    echo "Please set: export VOICE_CHANNEL_ID=your_channel_id"
    exit 1
fi

echo -e "${YELLOW}ℹ️  Configuration:${NC}"
echo "  DISCORD_TOKEN: ${DISCORD_TOKEN:0:20}..."
echo "  VOICE_CHANNEL_ID: $VOICE_CHANNEL_ID"

# Dockerfile のパス確認
if [ ! -f "bot/Dockerfile" ]; then
    echo -e "${RED}❌ Error: bot/Dockerfile not found${NC}"
    exit 1
fi

# ステップ 1: Docker イメージをビルド
echo -e "\n${YELLOW}[1/4] Building Discord Bot image...${NC}"
docker build -t airplay-discord-bot:latest ./bot

# ステップ 1.5: k3s にイメージをロード（containerd を使用している場合）
echo -e "\n${YELLOW}[1.5/4] Loading image into k3s...${NC}"
docker save airplay-discord-bot:latest | sudo ctr -n=k8s.io image import - 2>/dev/null || \
docker save airplay-discord-bot:latest | sudo k3s ctr -n=k8s.io image import - 2>/dev/null || \
echo "⚠️  Could not auto-load image, trying alternative method..."

# ステップ 2: Namespace 作成
echo -e "\n${YELLOW}[2/4] Creating Kubernetes namespace...${NC}"
kubectl apply -f k8s/namespace.yaml

# ステップ 3: ConfigMap 作成（環境変数を注入）
echo -e "\n${YELLOW}[3/4] Creating ConfigMaps...${NC}"
kubectl apply -f k8s/shairport-configmap.yaml

# Discord 環境変数を含む ConfigMap を動的に作成
kubectl create configmap discord-config \
  --from-literal=DISCORD_TOKEN="$DISCORD_TOKEN" \
  --from-literal=VOICE_CHANNEL_ID="$VOICE_CHANNEL_ID" \
  -n airplay \
  --dry-run=client -o yaml | kubectl apply -f -

# ステップ 4: Deployments をデプロイ
echo -e "\n${YELLOW}[4/4] Deploying Kubernetes resources...${NC}"
kubectl apply -f k8s/airplay-bridge-deployment.yaml

# デプロイ状況確認
echo -e "\n${GREEN}✅ Deployment started!${NC}"
echo -e "\n${YELLOW}Waiting for pods to be ready...${NC}"

# Pod が ready になるまで待機
kubectl wait --for=condition=ready pod \
  -l app=shairport-sync -n airplay \
  --timeout=120s 2>/dev/null || true

kubectl wait --for=condition=ready pod \
  -l app=discord-bot -n airplay \
  --timeout=120s 2>/dev/null || true

# 状態表示
echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Status:${NC}"
echo -e "${GREEN}========================================${NC}"
kubectl get pods -n airplay

# ログストリーミング開始
echo -e "\n${YELLOW}📋 Discord Bot Logs:${NC}"
kubectl logs -f deployment/discord-bot -n airplay 2>/dev/null || echo "Waiting for pod to start..."
