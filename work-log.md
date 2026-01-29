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
    "Account": "792867124641",
    "Arn": "arn:aws:iam::792867124641:user/hiroyannnn"
}
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

## 3. 手動デプロイ（初回検証）

### Docker イメージビルド & プッシュ
```bash
# ECR ログイン
$ aws ecr get-login-password --region ap-northeast-1 | docker login --username AWS --password-stdin 792867124641.dkr.ecr.ap-northeast-1.amazonaws.com

# x86_64 向けにビルド（Fargate 用）
$ docker build --platform linux/amd64 -t 792867124641.dkr.ecr.ap-northeast-1.amazonaws.com/spike-ecs-bg-dev:v2 .
$ docker push 792867124641.dkr.ecr.ap-northeast-1.amazonaws.com/spike-ecs-bg-dev:v2
```

### ECS デプロイ
```bash
# タスク定義を登録
$ aws ecs register-task-definition --cli-input-json file:///tmp/task-def-new.json
arn:aws:ecs:ap-northeast-1:792867124641:task-definition/spike-ecs-bg-task-dev:3

# サービス更新
$ aws ecs update-service --cluster spike-ecs-bg-cluster-dev --service spike-ecs-bg-service-dev --task-definition spike-ecs-bg-task-dev:3 --force-new-deployment
```

---

## 4. GitHub Actions CI/CD

### セットアップ
```bash
# GitHub Secrets に AWS_ROLE_ARN を設定
$ gh secret set AWS_ROLE_ARN --body "arn:aws:iam::792867124641:role/spike-ecs-bg-github-actions-dev"

# コード変更をプッシュ
$ git add . && git commit -m "feat: Add ECS Fargate infrastructure" && git push
```

### デプロイ結果
```
✓ Deploy to ECS (4m51s)
  ✓ Configure AWS credentials (OIDC)
  ✓ Login to Amazon ECR
  ✓ Build, tag, and push image to Amazon ECR
  ✓ Download task definition
  ✓ Render Amazon ECS task definition
  ✓ Deploy Amazon ECS task definition
```

### サービス状態
```json
{
    "running": 1,
    "desired": 1,
    "taskDef": "arn:aws:ecs:ap-northeast-1:792867124641:task-definition/spike-ecs-bg-task-dev:4"
}
```

---

## 5. 動作確認

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

---

## 6. リソース一覧

| リソース | 名前/ARN |
|---------|---------|
| VPC | spike-ecs-bg-vpc-dev |
| ALB | spike-ecs-bg-alb-dev |
| ALB DNS | spike-ecs-bg-alb-dev-188059054.ap-northeast-1.elb.amazonaws.com |
| ECS Cluster | spike-ecs-bg-cluster-dev |
| ECS Service | spike-ecs-bg-service-dev |
| Task Definition | spike-ecs-bg-task-dev:4 |
| ECR | 792867124641.dkr.ecr.ap-northeast-1.amazonaws.com/spike-ecs-bg-dev |
| GitHub Actions Role | arn:aws:iam::792867124641:role/spike-ecs-bg-github-actions-dev |

---

## 7. 月額コスト概算

| リソース | 月額 |
|---------|------|
| ALB | ~$16-22 |
| Fargate (0.25 vCPU / 512MB × 1) | ~$9 |
| ECR | ~$0.1 |
| CloudWatch Logs | ~$0.5 |
| NAT Gateway | $0 (なし) |
| **合計** | **~$25-30** |

---

## 8. Blue/Green デプロイ検証

### 設定変更

```hcl
# terraform/ecs.tf
deployment_configuration {
  strategy             = "BLUE_GREEN"
  bake_time_in_minutes = 5
}

# terraform/alb.tf - 追加リソース
- aws_lb_target_group.ecs_green  # Green 用ターゲットグループ
- aws_lb_listener_rule.ecs       # Listener Rule（トラフィック制御用）

# terraform/iam.tf - 追加リソース
- aws_iam_role.ecs_bluegreen     # ECS B/G 用 IAM ロール
```

### 必要な IAM 権限
```json
{
  "Action": [
    "elasticloadbalancing:DescribeTargetGroups",
    "elasticloadbalancing:DescribeTargetHealth",  // 必須
    "elasticloadbalancing:DescribeListeners",
    "elasticloadbalancing:DescribeRules",
    "elasticloadbalancing:ModifyListener",
    "elasticloadbalancing:ModifyRule"
  ]
}
```

### デプロイ実行結果

| フェーズ | 時刻 | 状態 |
|---------|------|------|
| デプロイ開始 | 23:54 | GitHub Actions 実行 |
| Green タスク起動 | 23:58 | 新タスク開始 |
| Green healthy | 23:59 | ヘルスチェック通過 |
| トラフィック切替 | 00:01 | v2.0.0 に切替 |
| Blue 終了 | 00:07 | draining → 終了 |
| デプロイ完了 | 00:08 | COMPLETED |

### 確認コマンド
```bash
# B/G 設定確認
$ aws ecs describe-services --cluster spike-ecs-bg-cluster-dev \
    --services spike-ecs-bg-service-dev \
    --query 'services[0].deploymentConfiguration'
{
    "strategy": "BLUE_GREEN",
    "bakeTimeInMinutes": 5
}

# デプロイ後
$ curl http://spike-ecs-bg-alb-dev-188059054.ap-northeast-1.elb.amazonaws.com/health
{"status":"healthy","version":"2.0.0"}
```

---

## 9. 知見・注意点

1. **ECS ネイティブ B/G は CodeDeploy 不要**
   - `deployment_configuration { strategy = "BLUE_GREEN" }` のみで OK
   - `aws-actions/amazon-ecs-deploy-task-definition` そのまま使用可能

2. **必要なリソース**
   - 2つ目のターゲットグループ（Green 用）
   - Listener Rule（default_action ではなく Rule で管理）
   - IAM ロール（ELB 操作権限）

3. **bake_time_in_minutes**
   - Green が healthy になってからトラフィック切替までの待機時間
   - この間に Green 環境をテスト可能

4. **IAM 権限エラー**
   - `DescribeTargetHealth` 権限がないと B/G デプロイが停止する
   - `RegisterTargets` / `DeregisterTargets` も必要
   - エラーは `aws ecs describe-services` の events で確認

---

## 10. Production 環境 (Approval フロー検証)

### Terraform Workspace 構成
```bash
# dev 環境（default workspace）
$ terraform workspace select default
$ terraform apply -var-file=environments/dev.tfvars

# prod 環境（prod workspace）
$ terraform workspace new prod
$ terraform apply -var-file=environments/prod.tfvars
```

### environments/prod.tfvars
```hcl
aws_region     = "ap-northeast-1"
project_name   = "spike-ecs-bg"
environment    = "prod"
github_repo    = "hiroyannnn/spike-ecs-bg-deploy"
container_port = 8080
desired_count  = 2  # prod は 2 タスク
```

### GitHub 設定コマンド

```bash
# リポジトリを Public に変更（Environment Protection は Public or 有料プランが必要）
$ gh repo edit --visibility public --accept-visibility-change-consequences

# prod 用の AWS Role ARN を Secret に設定
$ gh secret set AWS_ROLE_ARN_PROD \
    --body "arn:aws:iam::792867124641:role/spike-ecs-bg-github-actions-prod"

# production Environment を作成
$ gh api repos/hiroyannnn/spike-ecs-bg-deploy/environments/production -X PUT

# Approval 必須の Reviewer を設定
$ USER_ID=$(gh api user --jq '.id')
$ gh api repos/hiroyannnn/spike-ecs-bg-deploy/environments/production -X PUT \
    --input - <<EOF
{
  "reviewers": [{"type": "User", "id": $USER_ID}]
}
EOF
```

### Terraform 出力 (prod)
```
alb_dns_name            = "spike-ecs-bg-alb-prod-1116112328.ap-northeast-1.elb.amazonaws.com"
ecr_repository_url      = "792867124641.dkr.ecr.ap-northeast-1.amazonaws.com/spike-ecs-bg-prod"
ecs_cluster_name        = "spike-ecs-bg-cluster-prod"
ecs_service_name        = "spike-ecs-bg-service-prod"
github_actions_role_arn = "arn:aws:iam::792867124641:role/spike-ecs-bg-github-actions-prod"
```

### 初回イメージプッシュ
```bash
# ECR ログイン
$ aws ecr get-login-password --region ap-northeast-1 | \
    docker login --username AWS --password-stdin 792867124641.dkr.ecr.ap-northeast-1.amazonaws.com

# prod ECR にイメージをプッシュ
$ docker build --platform linux/amd64 \
    -t 792867124641.dkr.ecr.ap-northeast-1.amazonaws.com/spike-ecs-bg-prod:initial .
$ docker push 792867124641.dkr.ecr.ap-northeast-1.amazonaws.com/spike-ecs-bg-prod:initial

# タスク定義を更新してサービス起動
$ aws ecs describe-task-definition --task-definition spike-ecs-bg-task-prod \
    --query 'taskDefinition' > /tmp/task-def-prod.json
# image を initial に変更後
$ aws ecs register-task-definition --cli-input-json file:///tmp/task-def-prod-new.json
$ aws ecs update-service --cluster spike-ecs-bg-cluster-prod \
    --service spike-ecs-bg-service-prod \
    --task-definition spike-ecs-bg-task-prod:2 --force-new-deployment
```

### Approval ワークフロー実行
```bash
# prod デプロイワークフローを手動実行
$ gh workflow run deploy-prod.yml

# ワークフロー状態確認
$ gh run list --workflow=deploy-prod.yml --limit 1
waiting  Deploy to ECS (Production)  workflow_dispatch

# → GitHub UI で承認後、デプロイ実行
```

### prod 環境動作確認
```bash
$ curl http://spike-ecs-bg-alb-prod-1116112328.ap-northeast-1.elb.amazonaws.com/health
{"status":"healthy","version":"2.0.0"}
```

---

## 11. B/G デプロイに必要な IAM 権限（完全版）

```json
{
  "Action": [
    "elasticloadbalancing:DescribeTargetGroups",
    "elasticloadbalancing:DescribeTargetHealth",
    "elasticloadbalancing:DescribeListeners",
    "elasticloadbalancing:DescribeRules",
    "elasticloadbalancing:ModifyListener",
    "elasticloadbalancing:ModifyRule",
    "elasticloadbalancing:RegisterTargets",
    "elasticloadbalancing:DeregisterTargets"
  ],
  "Resource": "*"
}
```

---

## 12. リソース削除手順

検証終了後、以下の順序で削除:

```bash
# prod 環境削除
$ terraform workspace select prod
$ terraform destroy -var-file=environments/prod.tfvars -auto-approve

# dev 環境削除
$ terraform workspace select default
$ terraform destroy -var-file=environments/dev.tfvars -auto-approve

# GitHub Environment 削除
$ gh api repos/hiroyannnn/spike-ecs-bg-deploy/environments/production -X DELETE
```

---

## 13. 次のステップ

1. **sales-ops への適用**
   - 今回の知見・IAM 権限設定を反映
   - Terraform workspace または別ディレクトリで環境分離
