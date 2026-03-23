# Setup Instructions — Day by Day

## Day 1: AWS + Python environment setup

### Step 1 — Create AWS free tier account
1. Go to aws.amazon.com → click "Create a Free Account"
2. Enter your email, choose a username, set a strong password
3. Select "Personal" account type
4. Enter credit card (required but won't be charged if you stay in free tier)
5. Choose "Basic support" (free)

**IMMEDIATELY after account creation — set a billing alert:**
1. Go to AWS Console → search "Billing" → click "Billing and Cost Management"
2. Click "Budgets" in left sidebar → "Create budget"
3. Choose "Zero spend budget" — this alerts you if ANY charge occurs
4. Add your email. Done. You will never be surprised by a bill.

---

### Step 2 — Create S3 bucket
S3 is Amazon's cloud storage. Think of it as a hard drive in the cloud.
Your bucket is where ALL your data lives — raw files, processed Parquet, query results, AI memos.

1. AWS Console → search "S3" → click "Create bucket"
2. Bucket name: `layoff-intelligence-YOURNAME` (must be globally unique)
3. Region: `us-east-1` (US East — cheapest, most services available)
4. Block all public access: YES (keep checked — your data stays private)
5. Versioning: leave off
6. Click "Create bucket"

**Create these folders inside your bucket** (click bucket name → Create folder):
- `raw/layoffs/` — raw CSV from Layoffs.fyi lands here
- `raw/bls/` — raw JSON from BLS API lands here
- `processed/` — clean Parquet files after Glue ETL land here
- `athena-results/` — Athena saves query results here automatically
- `memos/` — OpenAI-generated analyst memos land here (Day 4)

---

### Step 3 — Create IAM user + access keys
IAM = Identity and Access Management. This is how your Python scripts
on your Mac are allowed to talk to AWS. Never use your root account credentials.

1. AWS Console → search "IAM" → click "Users" → "Create user"
2. Username: `layoff-project-user`
3. Check "Provide user access to AWS Management Console": NO
4. Click Next → "Attach policies directly"
5. Search and attach these 4 policies:
   - `AmazonS3FullAccess`
   - `AmazonAthenaFullAccess`
   - `AWSGlueConsoleFullAccess`
   - `AWSLambda_FullAccess`
6. Click "Create user"
7. Click on the user → "Security credentials" tab → "Create access key"
8. Use case: "Local code" → Next → Create
9. **COPY BOTH KEYS NOW — you can't see the secret key again**
10. Paste them into your `.env` file (never commit .env to GitHub)

---

### Step 4 — Install Python environment on Mac

Open Terminal on your Mac and run these commands one by one.
Each command is explained so you know what it does.

```bash
# Check if Homebrew is installed (Mac package manager)
# If you see "command not found", install it first:
# /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew --version

# Install pyenv — lets you manage multiple Python versions
# Without pyenv, Mac uses system Python which can cause conflicts
brew install pyenv

# Add pyenv to your shell so it loads every time you open Terminal
echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.zshrc
echo 'export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.zshrc
echo 'eval "$(pyenv init -)"' >> ~/.zshrc
source ~/.zshrc

# Install Python 3.11 (stable, well-supported by all libraries we use)
pyenv install 3.11.7
pyenv global 3.11.7

# Verify — should print Python 3.11.7
python --version
```

---

### Step 5 — Clone repo and install dependencies

```bash
# Navigate to where you keep projects
cd ~/Documents

# Clone your GitHub repo (replace with your actual repo URL)
git clone https://github.com/YOURUSERNAME/layoff-intelligence.git
cd layoff-intelligence

# Create a virtual environment — isolates this project's packages
# from everything else on your Mac
python -m venv venv

# Activate it — you must do this every time you open a new Terminal session
source venv/bin/activate
# You'll see (venv) appear at the start of your terminal prompt

# Install all required packages from requirements.txt
pip install -r requirements.txt

# Verify boto3 (AWS SDK) installed correctly
python -c "import boto3; print('boto3 OK')"
# Should print: boto3 OK
```

---

### Step 6 — Configure AWS CLI

```bash
# Install AWS CLI via Homebrew
brew install awscli

# Configure it with your IAM access keys
aws configure
# It will ask you 4 questions:
# AWS Access Key ID: [paste from Step 3]
# AWS Secret Access Key: [paste from Step 3]
# Default region name: us-east-1
# Default output format: json

# Test it works — should list your S3 bucket
aws s3 ls
# You should see: layoff-intelligence-YOURNAME
```

---

### Step 7 — Create .env file

```bash
# In your project folder, copy the example file
cp .env.example .env

# Open it in any text editor and fill in your values
# On Mac: open -e .env
# Or use VS Code: code .env
```

Fill in:
- `AWS_ACCESS_KEY_ID` — from Step 3
- `AWS_SECRET_ACCESS_KEY` — from Step 3
- `S3_BUCKET_NAME` — the bucket name you chose in Step 2
- Leave OpenAI and BLS keys blank for now (Day 2 and Day 4)

---

### Step 8 — Set up Glue database

AWS Glue is the ETL (Extract, Transform, Load) service.
The "database" here is just a metadata catalog — it tells Athena
what tables exist and where the data lives in S3.

1. AWS Console → search "AWS Glue" → "Databases" → "Add database"
2. Name: `layoff_db`
3. Click Create

Now create a Crawler (the thing that reads your S3 files and builds the table schema):
1. Glue → "Crawlers" → "Create crawler"
2. Name: `layoff-processed-crawler`
3. Data source: S3 → `s3://layoff-intelligence-YOURNAME/processed/`
4. IAM role: Create new → `AWSGlueServiceRole-layoff`
5. Target database: `layoff_db`
6. Schedule: "On demand" (you run it manually for now)
7. Create crawler
(You'll run it after Day 2 when processed/ has actual data in it)

---

### Step 9 — Set up Athena

Athena is Amazon's SQL query engine. It reads files directly from S3
and lets you query them with standard SQL — no database server needed.

1. AWS Console → search "Athena" → "Query editor"
2. First time: it asks for a query result location
3. Click "Edit settings" → set to: `s3://layoff-intelligence-YOURNAME/athena-results/`
4. Save

Test it works — run this in the Athena query editor:
```sql
SHOW DATABASES;
-- Should show: layoff_db (and default)
```

