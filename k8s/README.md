# Minikube / OrbStack デプロイ手順

このディレクトリは、電子申請ワークフローをKubernetes上で動かすための設定です。

## 構成

- Flaskアプリ: `Deployment/workflow-app`
- MySQL: `Deployment/workflow-db`
- MySQL永続化: `PersistentVolumeClaim/mysql-data`
- アプリ公開: `Service/workflow-app` NodePort `30080`
- DB初期化: `db/init.sql` を `ConfigMap/mysql-initdb` として投入

## 1. Minikubeを起動

一括で起動・デプロイ・ポートフォワードまで行う場合は、プロジェクト直下で以下を実行します。

```bash
./scripts/start-k8s-local.sh
```

このスクリプトは最後に確認用のポートフォワードを起動します。

```text
http://localhost:5002
```

停止する場合は、スクリプトを実行しているターミナルで `Ctrl + C` を押します。

発表時にKubernetes Service経由で見せる場合は、別のターミナルで以下を実行します。

```bash
minikube service workflow-app -n workflow-app
```

手順を分けて実行する場合は、以下のコマンドを順番に実行します。

OrbStackのDocker環境を使ってMinikubeを起動します。

```bash
minikube start --driver=docker
```

使用するKubernetesコンテキストを確認します。

```bash
kubectl config current-context
kubectl get nodes
```

## 2. アプリのDockerイメージをMinikube内にビルド

```bash
eval $(minikube docker-env)
docker build -t workflow-app:local .
```

## 3. NamespaceとSecretを作成

```bash
kubectl apply -f k8s/namespace.yaml
cp -n .env.example .env
```

`.env` の秘密鍵とパスワードを設定した後、次を実行します。

```bash
set -a
. ./.env
set +a

kubectl -n workflow-app create secret generic workflow-secrets \
  --from-literal=FLASK_SECRET_KEY="$FLASK_SECRET_KEY" \
  --from-literal=DB_NAME="$DB_NAME" \
  --from-literal=DB_USER="$DB_USER" \
  --from-literal=DB_PASSWORD="$DB_PASSWORD" \
  --from-literal=MYSQL_ROOT_PASSWORD="$MYSQL_ROOT_PASSWORD" \
  --dry-run=client -o yaml | kubectl apply -f -
```

## 4. DB初期化SQLをConfigMapとして登録

```bash
kubectl -n workflow-app create configmap mysql-initdb \
  --from-file=init.sql=db/init.sql \
  --dry-run=client -o yaml | kubectl apply -f -
```

## 5. MySQLとアプリをデプロイ

```bash
kubectl apply -f k8s/mysql.yaml
kubectl -n workflow-app rollout status deployment/workflow-db

kubectl apply -f k8s/app.yaml
kubectl -n workflow-app rollout status deployment/workflow-app
```

## 6. アプリを開く

```bash
minikube service workflow-app -n workflow-app
```

URLだけ確認したい場合:

```bash
minikube service workflow-app -n workflow-app --url
```

NodePortで開く場合:

```text
http://<minikube-ip>:30080
```

`minikube-ip` は以下で確認できます。

```bash
minikube ip
```

## 確認コマンド

```bash
kubectl -n workflow-app get pods
kubectl -n workflow-app get svc
kubectl -n workflow-app logs deployment/workflow-app
kubectl -n workflow-app logs deployment/workflow-db
```

## 初期化し直す場合

MySQLの永続ボリュームを消すと、次回起動時に `db/init.sql` から初期化されます。

```bash
./scripts/reset-k8s.sh
./scripts/start-k8s-local.sh
```

起動スクリプトを使わずに再作成する場合は、前述の手順でSecretを作成してから次を実行します。

```bash
kubectl -n workflow-app create configmap mysql-initdb \
  --from-file=init.sql=db/init.sql \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f k8s/mysql.yaml
kubectl apply -f k8s/app.yaml
```

## プライベートクラウド上で使う場合

プライベートクラウド上のKubernetesクラスタでも、同じマニフェストを利用できます。

変更が必要になりやすい箇所:

- `k8s/app.yaml` の `image`
- `k8s/app.yaml` の `Service` 種別
- `k8s/mysql.yaml` のストレージ容量
- `.env` から作成するKubernetes Secretの値

コンテナレジストリを使う場合は、アプリイメージをプッシュしてから `image` を差し替えます。

```bash
docker build -t <private-registry>/workflow-app:1.0.0 .
docker push <private-registry>/workflow-app:1.0.0
```

その後、`k8s/app.yaml` の以下を変更します。

```yaml
image: <private-registry>/workflow-app:1.0.0
imagePullPolicy: IfNotPresent
```
