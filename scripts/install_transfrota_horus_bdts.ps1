[CmdletBinding()]
param(
    [string]$HorusDbHost = '10.11.89.202',
    [int]$HorusDbPort = 5432,
    [string]$HorusDbName = 'horus',
    [string]$HorusDbUser = 'looker',
    [string]$VpsApiUrl = 'https://transfrota.digital',
    [int]$ManagementId = 49,
    [int]$LookbackDays = 90,
    [int]$BatchLimit = 100
)

$ErrorActionPreference = 'Stop'
$TaskName = 'Transfrota - Sincronizar Horus BDTS'
$ProjectRoot = 'D:\gestao_frotas'
$RunnerPath = Join-Path $ProjectRoot 'scripts\run_transfrota_horus_bdts.ps1'
$ConfigDirectory = Join-Path $env:LOCALAPPDATA 'Transfrota'
$ConfigPath = Join-Path $ConfigDirectory 'horus-bdts.config.clixml'
$StatePath = Join-Path $ConfigDirectory 'horus-bdts-state.json'
$LegacyStatePath = Join-Path $ProjectRoot '.bdt_horus_sync_state.json'

if (!(Test-Path -LiteralPath $RunnerPath)) { throw "Executor não encontrado: $RunnerPath" }
if ($BatchLimit -lt 1) { throw 'BatchLimit deve ser maior que zero.' }
New-Item -ItemType Directory -Force -Path $ConfigDirectory | Out-Null

# Keep the existing watermark when migrating to the absolute per-user state.
# The source is deliberately retained as a recoverable historical copy.
if (!(Test-Path -LiteralPath $StatePath) -and (Test-Path -LiteralPath $LegacyStatePath)) {
    Copy-Item -LiteralPath $LegacyStatePath -Destination $StatePath -ErrorAction Stop
}

# The two secrets never enter command history, stdout, the repository, or task XML.
$horusPassword = Read-Host 'Senha do PostgreSQL do Hórus' -AsSecureString
$syncToken = Read-Host 'Token VPS_SYNC_TOKEN/FLEET_SYNC_TOKEN' -AsSecureString
if ($horusPassword.Length -eq 0 -or $syncToken.Length -eq 0) { throw 'Os dois segredos são obrigatórios.' }

[pscustomobject]@{
    HorusDbHost = $HorusDbHost; HorusDbPort = $HorusDbPort; HorusDbName = $HorusDbName; HorusDbUser = $HorusDbUser
    HorusDbPassword = $horusPassword; VpsApiUrl = $VpsApiUrl.TrimEnd('/'); VpsSyncToken = $syncToken
    ManagementId = $ManagementId; LookbackDays = $LookbackDays; BatchLimit = $BatchLimit
} | Export-Clixml -LiteralPath $ConfigPath -Force

$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -WorkingDirectory $ProjectRoot -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$RunnerPath`" -Limit $BatchLimit"
$trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 14) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "Configuração DPAPI salva em $ConfigPath para $currentUser."
Write-Host "Tarefa '$TaskName' criada. Ela exige que $currentUser esteja conectado (DPAPI de usuário)."
