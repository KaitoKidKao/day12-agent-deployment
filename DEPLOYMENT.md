# Deployment Information

## Public URL
https://day12-nguyentricao-production.up.railway.app/docs

## Platform
Railway

## Test Commands

> [!IMPORTANT]
> **Windows Users:** These commands use `curl.exe` to ensure they run correctly in PowerShell.

### 1. App Info (Root)
```bash
curl.exe -X GET "https://day12-nguyentricao-production.up.railway.app/" -H "accept: application/json"
```

### 2. Health Check
```bash
curl.exe -X GET "https://day12-nguyentricao-production.up.railway.app/health"
```

### 3. Service Readiness
```bash
curl.exe -X GET "https://day12-nguyentricao-production.up.railway.app/ready"
```

### 4. AI Agent Test (Auth Required)
```bash
curl.exe -X POST "https://day12-nguyentricao-production.up.railway.app/ask" -H "X-API-Key: dev-key-change-me" -H "Content-Type: application/json" -d "{\"user_id\": \"test-user\", \"question\": \"Hello, what is your version?\"}"
```

### 5. Metrics & Budget
```bash
curl.exe -X GET "https://day12-nguyentricao-production.up.railway.app/metrics" -H "X-API-Key: dev-key-change-me"
```

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
```

##  Pre-Submission Checklist

- [x] Repository is public (or instructor has access)
- [x] `MISSION_ANSWERS.md` completed with all exercises
- [x] `DEPLOYMENT.md` has working public URL
- [x] All source code in `app/` directory
- [x] `README.md` has clear setup instructions
- [x] No `.env` file committed (only `.env.example`)
- [x] No hardcoded secrets in code
- [x] Public URL is accessible and working
- [x] Screenshots included in `screenshots/` folder
- [x] Repository has clear commit history

---