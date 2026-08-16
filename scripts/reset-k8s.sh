#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

echo "workflow-app Namespaceを削除します"
kubectl delete namespace workflow-app --ignore-not-found=true

echo "削除完了を待ちます"
while kubectl get namespace workflow-app >/dev/null 2>&1; do
  sleep 2
done

echo "削除完了です。再作成する場合は ./scripts/start-k8s-local.sh を実行してください"
