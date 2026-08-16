#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  cp .env.example .env
  echo ".env を作成しました。公開環境では各パスワードを必ず変更してください。"
fi

echo "Docker Compose版を起動します"
docker compose up -d --build

echo "起動状態"
docker compose ps

echo "ブラウザで http://localhost:5001 を開いてください"
