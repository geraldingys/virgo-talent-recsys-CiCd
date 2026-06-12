# Panduan Setup AWS — Virgo Talent RecSys

## Prasyarat

- [ ] AWS CLI terinstall: `aws --version`
- [ ] Sudah login: `aws configure` (masukkan Access Key, Secret, region: `ap-southeast-1`)
- [ ] Docker Desktop berjalan

---

## Step 1 — Buat ECR Repository

```bash
aws ecr create-repository \
  --repository-name virgo-recsys \
  --region ap-southeast-1
```

Catat nilai `repositoryUri` dari output (format: `ACCOUNT_ID.dkr.ecr.ap-southeast-1.amazonaws.com/virgo-recsys`).

---

## Step 2 — Buat ECS Cluster

```bash
aws ecs create-cluster \
  --cluster-name virgo-cluster \
  --capacity-providers FARGATE \
  --region ap-southeast-1
```

---

## Step 3 — Buat CloudWatch Log Group

```bash
aws logs create-log-group \
  --log-group-name /ecs/virgo-api \
  --region ap-southeast-1
```

---

## Step 4 — Buat IAM Roles

### 4a. ECS Task Execution Role (untuk pull image & baca secrets)

Buat via AWS Console:
1. Pergi ke **IAM → Roles → Create role**
2. Trusted entity: **AWS service → Elastic Container Service Task**
3. Attach policy: `AmazonECSTaskExecutionRolePolicy` (managed)
4. Tambah inline policy dari file `infra/iam-policy.json`
5. Nama role: `ecsTaskExecutionRole`

### 4b. Virgo Task Role (untuk app runtime)

```bash
# Buat role
aws iam create-role \
  --role-name virgo-task-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "ecs-tasks.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

# Attach policy dari file
aws iam put-role-policy \
  --role-name virgo-task-role \
  --policy-name virgo-task-policy \
  --policy-document file://infra/iam-policy.json
```

---

## Step 5 — Simpan Secrets di AWS Secrets Manager

```bash
aws secretsmanager create-secret \
  --name virgo/production \
  --region ap-southeast-1 \
  --secret-string '{
    "NEO4J_URI":             "neo4j+s://46a41b78.databases.neo4j.io",
    "NEO4J_USERNAME":        "46a41b78",
    "NEO4J_PASSWORD":        "ISIAN_PASSWORD",
    "NEO4J_DATABASE":        "46a41b78",
    "OLLAMA_ENDPOINT":       "http://ISIAN_URL_OLLAMA/api/generate",
    "JWT_TOKEN":             "Bearer ISIAN_TOKEN",
    "OLLAMA_MODEL":          "qwen3:8b",
    "OLLAMA_TIMEOUT":        "180",
    "GOOGLE_SPREADSHEET_ID": "1LAnhPwD0G5DvM02HxvfpvxBOuXSIOc3xdLZjaHhdWM0"
  }'
```

> **PENTING**: Ganti `ISIAN_*` dengan nilai aktual. Jangan commit ke Git.

---

## Step 6 — Update `infra/task-definition.json`

Ganti semua `ACCOUNT_ID` di file `infra/task-definition.json` dengan AWS Account ID kamu:

```bash
# Cek Account ID kamu
aws sts get-caller-identity --query Account --output text

# Ganti di file (PowerShell)
(Get-Content infra/task-definition.json) -replace 'ACCOUNT_ID', '123456789012' | Set-Content infra/task-definition.json
```

---

## Step 7 — Register Task Definition

```bash
aws ecs register-task-definition \
  --cli-input-json file://infra/task-definition.json \
  --region ap-southeast-1
```

---

## Step 8 — Buat ECS Service + ALB (via Console)

Lebih mudah via AWS Console:

1. Pergi ke **ECS → Clusters → virgo-cluster → Create Service**
2. Launch type: **FARGATE**
3. Task definition: **virgo-api** (versi terbaru)
4. Service name: **virgo-api**
5. Desired tasks: **1**
6. Load balancer: **Application Load Balancer**
   - Create new ALB: `virgo-alb`
   - Listener: **HTTPS port 443** (butuh SSL certificate di ACM)
   - atau **HTTP port 80** dulu untuk testing
   - Target group: **virgo-tg**, health check path: `/health`
7. VPC & Subnets: pilih public subnets
8. Security Group: allow inbound port 443 (atau 80) dari internet, allow outbound port 8000 ke container

---

## Step 9 — Set GitHub Actions Secrets

Di GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret Name | Nilai |
|---|---|
| `AWS_ACCESS_KEY_ID` | IAM user access key |
| `AWS_SECRET_ACCESS_KEY` | IAM user secret key |
| `AWS_ACCOUNT_ID` | AWS Account ID (12 digit) |

> Neo4j password dan credentials lain **tidak perlu** di GitHub Secrets karena sudah di AWS Secrets Manager yang direferensikan dari task-definition.json.

---

## Step 10 — Push ke main & trigger deploy

```bash
git add .
git commit -m "feat: deploy to AWS ECS with Neo4j Aura"
git push origin main
```

GitHub Actions akan otomatis:
1. Build Docker image
2. Push ke ECR
3. Deploy ke ECS Fargate

Monitor di: **GitHub → Actions tab**

---

## Verifikasi

```bash
# Health check (ganti dengan ALB DNS dari console)
curl https://<ALB-DNS>/health
# Expected: {"status":"healthy"}

# Swagger docs
open https://<ALB-DNS>/docs
```

---

## Troubleshooting

```bash
# Lihat log container ECS
aws logs tail /ecs/virgo-api --follow --region ap-southeast-1

# Lihat status service
aws ecs describe-services \
  --cluster virgo-cluster \
  --services virgo-api \
  --region ap-southeast-1

# Force redeploy tanpa code change
aws ecs update-service \
  --cluster virgo-cluster \
  --service virgo-api \
  --force-new-deployment \
  --region ap-southeast-1
```
