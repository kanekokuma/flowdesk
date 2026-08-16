#!/bin/sh
set -eu

APP_PORT="${APP_PORT:-5002}"
NAMESPACE="workflow-app"
DOCKER_CONTEXT="${DOCKER_CONTEXT:-orbstack}"
APP_IMAGE="workflow-app:local-$(date +%Y%m%d%H%M%S)"

cd "$(dirname "$0")/.."

if ! docker context inspect "$DOCKER_CONTEXT" >/dev/null 2>&1; then
  echo "Docker context '$DOCKER_CONTEXT' が見つかりません。OrbStackがインストールされているか確認してください。" >&2
  exit 1
fi

echo "0. Docker contextを $DOCKER_CONTEXT に切り替えます"
docker context use "$DOCKER_CONTEXT" >/dev/null
if ! docker info >/dev/null 2>&1; then
  echo "OrbStackのDockerが起動していません。OrbStackを起動してから再実行してください。" >&2
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo ".env を作成しました。公開環境では各パスワードを必ず変更してください。"
fi

set -a
. ./.env
set +a

: "${FLASK_SECRET_KEY:?FLASK_SECRET_KEY must be set in .env}"
: "${DB_NAME:?DB_NAME must be set in .env}"
: "${DB_USER:?DB_USER must be set in .env}"
: "${DB_PASSWORD:?DB_PASSWORD must be set in .env}"
: "${MYSQL_ROOT_PASSWORD:?MYSQL_ROOT_PASSWORD must be set in .env}"

echo "1. Minikubeを起動します"
minikube start --driver=docker

echo "2. OrbStackでアプリイメージをビルドします"
docker build -t "$APP_IMAGE" .

echo "3. アプリイメージをMinikubeへ読み込みます"
minikube image load "$APP_IMAGE" --overwrite=true

echo "4. Kubernetesリソースを作成・更新します"
kubectl apply -f k8s/namespace.yaml
kubectl -n "$NAMESPACE" create secret generic workflow-secrets \
  --from-literal=FLASK_SECRET_KEY="$FLASK_SECRET_KEY" \
  --from-literal=DB_NAME="$DB_NAME" \
  --from-literal=DB_USER="$DB_USER" \
  --from-literal=DB_PASSWORD="$DB_PASSWORD" \
  --from-literal=MYSQL_ROOT_PASSWORD="$MYSQL_ROOT_PASSWORD" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n "$NAMESPACE" create configmap mysql-initdb \
  --from-file=init.sql=db/init.sql \
  --dry-run=client -o yaml | kubectl apply -f -

echo "5. MySQLを起動します"
kubectl apply -f k8s/mysql.yaml
kubectl -n "$NAMESPACE" rollout status deployment/workflow-db --timeout=180s

echo "6. アプリを起動します"
kubectl apply -f k8s/app.yaml
kubectl -n "$NAMESPACE" set image deployment/workflow-app app="$APP_IMAGE"
kubectl -n "$NAMESPACE" rollout status deployment/workflow-app --timeout=180s

echo "7. 起動状態"
kubectl -n "$NAMESPACE" get pods
kubectl -n "$NAMESPACE" get svc

echo "8. ブラウザで http://localhost:${APP_PORT} を開いてください"
echo "   停止する場合は、このターミナルで Ctrl + C を押します"
kubectl -n "$NAMESPACE" port-forward svc/workflow-app "${APP_PORT}:80"
