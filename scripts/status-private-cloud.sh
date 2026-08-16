#!/bin/sh
set -eu

NAMESPACE="workflow-app"

echo "Kubernetesコンテキスト"
kubectl config current-context

echo
echo "ノード"
kubectl get nodes -o wide

echo
echo "Pod"
kubectl -n "$NAMESPACE" get pods -o wide

echo
echo "Service"
kubectl -n "$NAMESPACE" get svc

echo
echo "PVC"
kubectl -n "$NAMESPACE" get pvc

echo
echo "アプリログ"
kubectl -n "$NAMESPACE" logs deployment/workflow-app --tail=20
