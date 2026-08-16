# コンテナ中心のクラウドネイティブ型プライベートクラウド構成

このアプリケーションは、企業内の電子申請・承認業務をWebアプリケーションとして実装したものです。
ローカル開発ではDocker Compose、本番に近いプライベートクラウド環境ではKubernetesを使う構成にしています。

## 目的

Docker Composeでアプリケーションをコンテナ化し、Kubernetes上にデプロイできるようにすることで、コンテナ中心のクラウドネイティブ型プライベートクラウド構成を実現します。

## 使用技術

- Docker
- Docker Compose
- Docker Desktop
- OrbStack
- Minikube
- Kubernetes
- Flask
- MySQL

## システム構成

```text
利用者のブラウザ
  |
  | HTTP
  v
Kubernetes Service: workflow-app
  |
  v
Pod: workflow-app
  |
  | DB_HOST=db
  v
Kubernetes Service: db
  |
  v
Pod: workflow-db
  |
  v
PersistentVolumeClaim: mysql-data
```

## Docker Compose版

Docker Compose版は、開発・動作確認用の構成です。

```text
docker-compose.yml
  app: Flaskアプリ
  db: MySQL
```

起動:

```bash
./scripts/start-compose.sh
```

URL:

```text
http://localhost:5001
```

## Kubernetes / Minikube版

Kubernetes版は、プライベートクラウド上での運用を想定した構成です。

```text
k8s/namespace.yaml
k8s/mysql.yaml
k8s/app.yaml
```

Secretはリポジトリへ保存せず、`start-k8s-local.sh` がGit管理対象外の `.env` から作成します。

起動:

```bash
./scripts/start-k8s-local.sh
```

アプリを開く場合:

```bash
minikube service workflow-app -n workflow-app
```

URLだけ確認する場合:

```bash
minikube service workflow-app -n workflow-app --url
```

## Kubernetesで使っているリソース

| リソース | 役割 |
|---|---|
| Namespace | アプリ用の領域を分ける |
| Deployment | FlaskアプリとMySQLのPodを管理する |
| Pod | 実際にコンテナが動く単位 |
| Service | Podへ安定してアクセスする入口 |
| Secret | DBパスワードなどを管理する |
| ConfigMap | DB初期化SQLをMySQLへ渡す |
| PVC | MySQLデータを永続化する |

## プライベートクラウドとして説明するポイント

この構成では、アプリケーションをコンテナ化し、Kubernetes上で管理しています。
アプリケーションサーバとデータベースサーバは別Podとして分離され、Serviceで通信します。
DB接続情報は `.env` からKubernetes Secretを作成して分離し、DB初期化SQLはConfigMapとして管理します。
MySQLデータはPVCで永続化します。

そのため、ローカルの単なるPython実行ではなく、Kubernetesを中心としたクラウドネイティブなプライベートクラウド構成として説明できます。

## 動作確認コマンド

```bash
./scripts/status-private-cloud.sh
```

個別に確認する場合:

```bash
kubectl config current-context
kubectl get nodes -o wide
kubectl -n workflow-app get pods -o wide
kubectl -n workflow-app get svc
kubectl -n workflow-app get pvc
kubectl -n workflow-app logs deployment/workflow-app --tail=20
```

## 初期化

Kubernetes版を最初から作り直す場合:

```bash
./scripts/reset-k8s.sh
./scripts/start-k8s-local.sh
```

## 補足

Docker DesktopとOrbStackは、どちらもDocker実行環境として使えます。
このプロジェクトでは、Docker Compose版でDockerの基本構成を確認し、OrbStack上のDocker環境でMinikubeを起動してKubernetes版を確認します。
