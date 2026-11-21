<#
.SYNOPSIS
  Host the whole system on one Google Compute Engine VM: the patient app, the
  monitoring stack, the doctor, Ollama, and the agent team (AGAI).

.DESCRIPTION
  Run from the repository root on the laptop. Idempotent: re-running it
  refreshes the secrets, the firewall rule and the two uploads.

    1. enables Compute Engine and Secret Manager
    2. copies the keys into Secret Manager (never printed, never in the image):
         .env       DOCTOR_API_KEY, GRAFANA_ADMIN_PASSWORD, MINIO_ROOT_PASSWORD
         AGAI/.env  ZAI_API_KEY, GITHUB_TOKEN
       and mints an A2A token for the agent team
    3. a service account that may read only those secrets
    4. a firewall rule opening the web ports to THIS computer's IP only
       (the agent team's UI has no login, and every run is billed)
    5. the VM, with deploy/gcp/startup.sh as its start-up script
    6. uploads what the repo cannot provide: a git bundle of the agent team at
       its current commit, and the knowledge-base build (DVC data)

  The VM then installs Docker and Ollama, pulls this repo from GitHub and runs
  deploy/gcp/vm-up.sh. The first boot takes about 20-30 minutes; follow it with
    gcloud compute ssh aid-vm --zone asia-south1-a --project gen-lang-client-0747635989 -- sudo tail -f /var/log/aid-startup.log

  The VM pulls origin/main from GitHub at every boot: push before (re)starting it.

.EXAMPLE
  ./deploy/gcp/create_vm.ps1
  ./deploy/gcp/create_vm.ps1 -Project my-project -Zone asia-south1-b
#>
param(
    # The project with GPU quota (1 x L4 in asia-south1, granted 2026-11-21). The
    # first project, monumento-cf0b5, was refused GPUs for lack of usage history.
    [string]$Project = "gen-lang-client-0747635989",
    # Singapore: on 2026-11-21 every asia-south1 zone was out of L4s (quota is not stock).
    [string]$Zone = "asia-southeast1-c",
    [string]$Name = "aid-vm",
    # 8 vCPU / 32 GB + one NVIDIA L4: Ollama on CPU alone was far too slow (4 vCPU:
    # chat p95 120 s vs the 40 s alert). startup.sh installs the GPU driver.
    [string]$MachineType = "g2-standard-8",
    [string]$AgaiDir = "AGAI",
    # Which key the agent team uses: "agai" = AGAI/.env ZAI_API_KEY (its paid plan),
    # "doctor" = .env DOCTOR_API_KEY (free flash models only; see deploy/agai/models.yaml).
    [ValidateSet("agai", "doctor")][string]$AgentKey = "agai",
    [string]$RepoUrl = "https://github.com/karthik14344/ai-incident-doctor.git"
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent)

function G([string[]]$a) {
    & gcloud @a --project $Project --quiet
    if ($LASTEXITCODE -ne 0) { throw "gcloud $($a -join ' ') failed" }
}
function Exists([string[]]$a) {
    & gcloud @a --project $Project --quiet *> $null
    return $LASTEXITCODE -eq 0
}
function EnvValue([string]$file, [string]$key) {
    $line = Get-Content $file -ErrorAction SilentlyContinue | Where-Object { $_ -match "^$key=(.+)$" } |
            Select-Object -First 1
    if ($line) { return ($line -replace "^$key=", "").Trim().Trim('"').Trim("'") }
    return ""
}
function Put-Secret([string]$name, [string]$value) {
    if (-not $value) { Write-Host "  $name - no value, skipped"; return }
    $tmp = [IO.Path]::GetTempFileName()
    try {
        [IO.File]::WriteAllText($tmp, $value)
        if (Exists @("secrets", "describe", $name)) {
            G @("secrets", "versions", "add", $name, "--data-file=$tmp") | Out-Null
        } else {
            G @("secrets", "create", $name, "--replication-policy=automatic", "--data-file=$tmp") | Out-Null
        }
        G @("secrets", "add-iam-policy-binding", $name, "--member=serviceAccount:$SA",
            "--role=roles/secretmanager.secretAccessor") | Out-Null
        Write-Host "  $name - stored"
    } finally { Remove-Item $tmp -Force }
}

Write-Host "1. APIs"
G @("services", "enable", "compute.googleapis.com", "secretmanager.googleapis.com")

Write-Host "2-3. service account + secrets"
$SA = "$Name@$Project.iam.gserviceaccount.com"
if (-not (Exists @("iam", "service-accounts", "describe", $SA))) {
    G @("iam", "service-accounts", "create", $Name, "--display-name=ai-incident-doctor VM")
    Start-Sleep -Seconds 10   # let the new account propagate before binding roles to it
}
Put-Secret "aid-doctor-api-key" (EnvValue ".env" "DOCTOR_API_KEY")
Put-Secret "aid-grafana-password" (EnvValue ".env" "GRAFANA_ADMIN_PASSWORD")
Put-Secret "aid-minio-password" (EnvValue ".env" "MINIO_ROOT_PASSWORD")
Put-Secret "aid-zai-api-key" ($(if ($AgentKey -eq "doctor") { EnvValue ".env" "DOCTOR_API_KEY" } else { EnvValue "$AgaiDir/.env" "ZAI_API_KEY" }))
Put-Secret "aid-github-token" (EnvValue "$AgaiDir/.env" "GITHUB_TOKEN")
if (-not (Exists @("secrets", "describe", "aid-a2a-token"))) {
    Put-Secret "aid-a2a-token" ([Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)))
}

Write-Host "4. firewall (this computer only)"
& "$PSScriptRoot/allow-my-ip.ps1" -Project $Project

Write-Host "5. VM"
$agaiRef = (git -C $AgaiDir rev-parse HEAD).Trim()
$meta = "aid-repo-url=$RepoUrl,aid-agai-ref=$agaiRef,aid-doctor-model=$(EnvValue '.env' 'DOCTOR_MODEL')"
if (Exists @("compute", "instances", "describe", $Name, "--zone", $Zone)) {
    G @("compute", "instances", "add-metadata", $Name, "--zone", $Zone, "--metadata", $meta,
        "--metadata-from-file", "startup-script=deploy/gcp/startup.sh")
    Write-Host "  $Name exists - metadata refreshed"
} else {
    # A VM with a GPU cannot be live-migrated: it must stop for host maintenance.
    $gpu = if ($MachineType -like "g2-*") { @("--maintenance-policy", "TERMINATE") } else { @() }
    G (@("compute", "instances", "create", $Name, "--zone", $Zone, "--machine-type", $MachineType,
        "--image-family", "ubuntu-2404-lts-amd64", "--image-project", "ubuntu-os-cloud",
        "--boot-disk-size", "80GB", "--boot-disk-type", "pd-balanced", "--tags", "aid",
        "--service-account", $SA, "--scopes", "cloud-platform",
        "--metadata", $meta, "--metadata-from-file", "startup-script=deploy/gcp/startup.sh") + $gpu)
}

Write-Host "6. uploads (agent team bundle + knowledge base)"
$up = Join-Path ([IO.Path]::GetTempPath()) "aid-upload"
New-Item -ItemType Directory -Force $up | Out-Null
git -C $AgaiDir bundle create "$up/agai.bundle" HEAD main 2>$null
if ($LASTEXITCODE -ne 0) { throw "git bundle failed" }
tar -czf "$up/kb.tar.gz" kb/documents kb/index kb/records.json
if ($LASTEXITCODE -ne 0) { throw "packing kb/ failed" }
for ($i = 0; $i -lt 30; $i++) {   # sshd needs a minute after create
    & gcloud compute scp "$up/agai.bundle" "$up/kb.tar.gz" "${Name}:/tmp/" --zone $Zone --project $Project --quiet
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 10
}
if ($LASTEXITCODE -ne 0) { throw "upload to the VM failed" }
# Bundle first, kb last: the start-up script waits until both are in place.
G @("compute", "ssh", $Name, "--zone", $Zone, "--command",
    "sudo mkdir -p /opt/aid && sudo mv /tmp/agai.bundle /opt/aid/ && sudo mv /tmp/kb.tar.gz /opt/aid/")
Remove-Item -Recurse -Force $up

$ip = (& gcloud compute instances describe $Name --zone $Zone --project $Project `
        --format "value(networkInterfaces[0].accessConfigs[0].natIP)").Trim()
Write-Host ""
Write-Host "Done. First boot takes ~20-30 min. Then:"
Write-Host "  app        http://${ip}:3001   (Incidents page shows the doctor + agent team)"
Write-Host "  agent team http://${ip}:8200"
Write-Host "  grafana    http://${ip}:3000   doctor http://${ip}:8100/health"
Write-Host "  progress   gcloud compute ssh $Name --zone $Zone -- sudo tail -f /var/log/aid-startup.log"
