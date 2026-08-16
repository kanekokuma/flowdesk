#!/bin/sh
set -eu

DOCKER_CONTEXT="${DOCKER_CONTEXT:-orbstack}"

cd "$(dirname "$0")/.."

if ! docker context inspect "$DOCKER_CONTEXT" >/dev/null 2>&1; then
  echo "Docker context '$DOCKER_CONTEXT' が見つかりません。OrbStackがインストールされているか確認してください。" >&2
  exit 1
fi

echo "1. Docker contextを $DOCKER_CONTEXT に切り替えます"
docker context use "$DOCKER_CONTEXT" >/dev/null
if ! docker info >/dev/null 2>&1; then
  echo "OrbStackのDockerが起動していません。OrbStackを起動してから再実行してください。" >&2
  exit 1
fi

echo "2. 既存のMinikube環境を削除します"
minikube delete --profile=minikube || true

echo "3. FlowDesk環境を最初から再構築します"
exec ./scripts/start-k8s-local.sh
