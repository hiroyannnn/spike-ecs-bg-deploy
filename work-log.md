# ECS Blue/Green デプロイ検証 作業ログ

## 概要
- **目的**: ECS Blue/Green デプロイ環境の検証
- **AWS アカウント**: 792867124641
- **リージョン**: ap-northeast-1
- **日時**: 2026-01-29

---

## 1. Terraform 構成作成

### 作成したファイル
```
terraform/
├── provider.tf    # AWS Provider (v6.30.0)
├── variables.tf   # 変数定義
├── vpc.tf         # VPC, Subnet x2, IGW, Route Table
├── alb.tf         # ALB, Target Group, Security Group
├── ecs.tf         # ECS Cluster, Service, Task Definition
├── ecr.tf         # ECR Repository
├── iam.tf         # IAM (OIDC, GitHub Actions Role, ECS Roles)
├── outputs.tf
└── terraform.tfvars
```

### 構成のポイント
- Public Subnet のみ（NAT Gateway なし、コスト削減）
- ECS タスクは `assign_public_ip = true` で ECR からイメージ取得
- ALB 経由でアクセス
- `health_check_grace_period_seconds = 60` で ALB ヘルスチェック猶予

---

## 2. Terraform 実行

### AWS アカウント確認
```bash
$ aws sts get-caller-identity
{
    "UserId": "AIDA3RGUQGWQ3TRV6527P",
    "Account": "792867124641",
    "Arn": "arn:aws:iam::792867124641:user/hiroyannnn"
}
```

### terraform init
```bash
$ cd terraform && terraform init

Initializing provider plugins...
- Installing hashicorp/aws v6.30.0...
Terraform has been successfully initialized!
```

### terraform apply
```bash
$ terraform apply -auto-approve

Apply complete! Resources: 24 added, 0 changed, 0 destroyed.

Outputs:
alb_dns_name            = "spike-ecs-bg-alb-dev-188059054.ap-northeast-1.elb.amazonaws.com"
ecr_repository_url      = "792867124641.dkr.ecr.ap-northeast-1.amazonaws.com/spike-ecs-bg-dev"
ecs_cluster_name        = "spike-ecs-bg-cluster-dev"
ecs_service_name        = "spike-ecs-bg-service-dev"
github_actions_role_arn = "arn:aws:iam::792867124641:role/spike-ecs-bg-github-actions-dev"
task_definition_family  = "spike-ecs-bg-task-dev"
```

---

## 3. サンプルアプリのデプロイ

### ECR ログイン
```bash
$ aws ecr get-login-password --region ap-northeast-1 | docker login --username AWS --password-stdin 792867124641.dkr.ecr.ap-northeast-1.amazonaws.com
Login Succeeded
```

### Docker イメージビルド & プッシュ
```bash
# x86_64 向けにビルド（Fargate 用）
$ docker build --platform linux/amd64 -t 792867124641.dkr.ecr.ap-northeast-1.amazonaws.com/spike-ecs-bg-dev:v2 .
$ docker push 792867124641.dkr.ecr.ap-northeast-1.amazonaws.com/spike-ecs-bg-dev:v2
```

### タスク定義の更新 & デプロイ
```bash
# 現在のタスク定義を取得してイメージを更新
$ aws ecs describe-task-definition --task-definition spike-ecs-bg-task-dev --query taskDefinition > /tmp/task-def.json
$ cat /tmp/task-def.json | jq '.containerDefinitions[0].image = "792867124641.dkr.ecr.ap-northeast-1.amazonaws.com/spike-ecs-bg-dev:v2"' > /tmp/task-def-new.json

# 新しいタスク定義を登録
$ aws ecs register-task-definition --cli-input-json file:///tmp/task-def-new.json
arn:aws:ecs:ap-northeast-1:792867124641:task-definition/spike-ecs-bg-task-dev:3

# サービス更新
$ aws ecs update-service --cluster spike-ecs-bg-cluster-dev --service spike-ecs-bg-service-dev --task-definition spike-ecs-bg-task-dev:3 --force-new-deployment
```

### アプリログ
```
INFO:     Started server process [1]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
INFO:     10.0.1.91:64712 - "GET /health HTTP/1.1" 200 OK
```

---

## 4. 動作確認

### ALB エンドポイント
```
http://spike-ecs-bg-alb-dev-188059054.ap-northeast-1.elb.amazonaws.com
```

### アクセス結果
```bash
$ curl http://spike-ecs-bg-alb-dev-188059054.ap-northeast-1.elb.amazonaws.com/health
{"status":"healthy","version":"1.0.0"}

$ curl http://spike-ecs-bg-alb-dev-188059054.ap-northeast-1.elb.amazonaws.com/
{"message":"Hello from ECS!","version":"1.0.0"}
```

### 最終サービス状態
```json
{
    "running": 1,
    "desired": 1,
    "taskDef": "arn:aws:ecs:ap-northeast-1:792867124641:task-definition/spike-ecs-bg-task-dev:3"
}
```

---

## 5. リソース一覧

| リソース | 名前/ARN |
|---------|---------|
| VPC | spike-ecs-bg-vpc-dev |
| ALB | spike-ecs-bg-alb-dev |
| ALB DNS | spike-ecs-bg-alb-dev-188059054.ap-northeast-1.elb.amazonaws.com |
| ECS Cluster | spike-ecs-bg-cluster-dev |
| ECS Service | spike-ecs-bg-service-dev |
| Task Definition | spike-ecs-bg-task-dev:3 |
| ECR | 792867124641.dkr.ecr.ap-northeast-1.amazonaws.com/spike-ecs-bg-dev |
| GitHub Actions Role | arn:aws:iam::792867124641:role/spike-ecs-bg-github-actions-dev |

---

## 6. 月額コスト概算

| リソース | 月額 |
|---------|------|
| ALB | ~$16-22 |
| Fargate (0.25 vCPU / 512MB × 1) | ~$9 |
| ECR | ~$0.1 |
| CloudWatch Logs | ~$0.5 |
| NAT Gateway | $0 (なし) |
| **合計** | **~$25-30** |

---

## 7. 次のステップ

1. **GitHub Actions 設定**
   - Secrets に `AWS_ROLE_ARN` を設定
   - `.github/workflows/deploy.yml` で CI/CD テスト

2. **Blue/Green デプロイへの移行**
   - AWS Provider 6.4.0+ で `deployment_configuration` に `strategy = "BLUE_GREEN"` を設定

3. **本番環境（sales-ops）への適用**
   - 今回の知見を反映
