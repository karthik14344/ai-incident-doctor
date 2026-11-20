<#
.SYNOPSIS
  Open the VM's web ports to this computer's current public IP only.

.DESCRIPTION
  The agent team's UI has no login and every run is billed, and Grafana /
  Prometheus / the doctor are not meant to be public. So the firewall admits a
  single address. Run this again from any new network (e.g. the presentation
  room); it replaces the previous address.

    3001 app (Incidents page)   3000 Grafana   8100 doctor   8200 agent team
    9090 Prometheus   9093 Alertmanager   9095 alert-sink   8000 gateway

.EXAMPLE
  ./deploy/gcp/allow-my-ip.ps1
#>
param(
    [string]$Project = "monumento-cf0b5",
    [string]$Rule = "aid-web-from-my-ip"
)
$ErrorActionPreference = "Stop"
$ip = (Invoke-RestMethod -Uri "https://api.ipify.org").Trim()
$ports = "tcp:3001,tcp:3000,tcp:8100,tcp:8200,tcp:9090,tcp:9093,tcp:9095,tcp:8000"
& gcloud compute firewall-rules describe $Rule --project $Project --quiet *> $null
if ($LASTEXITCODE -eq 0) {
    & gcloud compute firewall-rules update $Rule --project $Project --quiet --source-ranges "$ip/32" --allow $ports
} else {
    & gcloud compute firewall-rules create $Rule --project $Project --quiet --network default `
        --direction INGRESS --target-tags aid --source-ranges "$ip/32" --allow $ports
}
if ($LASTEXITCODE -ne 0) { throw "firewall update failed" }
Write-Host "  web ports open to $ip only"
