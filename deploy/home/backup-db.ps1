param(
    [string]$EnvFile = ".env.home",
    [string]$ComposeFile = "docker-compose.home.yml",
    [string]$BackupDir = "backups"
)

$ErrorActionPreference = "Stop"

$envValues = @{}
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match "^\s*([^#][^=]+)=(.*)$") {
            $envValues[$matches[1].Trim()] = $matches[2].Trim()
        }
    }
}

$postgresUser = $envValues["POSTGRES_USER"]
if ([string]::IsNullOrWhiteSpace($postgresUser)) {
    $postgresUser = "neu_bot"
}

$postgresDb = $envValues["POSTGRES_DB"]
if ([string]::IsNullOrWhiteSpace($postgresDb)) {
    $postgresDb = "neu_bot"
}

if (!(Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupPath = Join-Path $BackupDir "$postgresDb-$timestamp.sql"

docker compose -f $ComposeFile --env-file $EnvFile exec -T postgres pg_dump -U $postgresUser -d $postgresDb | Out-File -FilePath $backupPath -Encoding utf8

Write-Host "Backup written to $backupPath"
