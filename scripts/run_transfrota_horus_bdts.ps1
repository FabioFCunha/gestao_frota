[CmdletBinding()]
param(
    [switch]$DryRun,
    [int]$Limit = 100,
    [int[]]$ManagementIds = @(49, 125)
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = 'D:\gestao_frotas'
$PythonExe = 'D:\gestao_frotas\.venv\Scripts\python.exe'
$DataRoot = 'C:\Users\fferreira\AppData\Local\Transfrota'
$ConfigPath = Join-Path $DataRoot 'horus-bdts.config.clixml'
$StatePath = Join-Path $DataRoot 'horus-bdts-state.json'
$LogDirectory = Join-Path $DataRoot 'logs'
$LogPath = Join-Path $LogDirectory 'horus-bdts-sync.log'

function Write-SyncLog([string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ssK') $Message"
    Add-Content -LiteralPath $LogPath -Value $line -Encoding utf8
}

function Rotate-Logs {
    if ((Test-Path -LiteralPath $LogPath) -and (Get-Item -LiteralPath $LogPath).Length -gt 5MB) {
        for ($i = 4; $i -ge 1; $i--) {
            $old = "$LogPath.$i"
            $new = "$LogPath." + ($i + 1)
            if (Test-Path -LiteralPath $old) { Move-Item -LiteralPath $old -Destination $new -Force }
        }
        Move-Item -LiteralPath $LogPath -Destination "$LogPath.1" -Force
    }
}

try {
    if ($Limit -lt 1) { throw 'O limite do lote deve ser maior que zero.' }
    if (!(Test-Path -LiteralPath $PythonExe)) { throw "Python não encontrado: $PythonExe" }
    if (!(Test-Path -LiteralPath $ConfigPath)) { throw "Configuração DPAPI não encontrada: $ConfigPath" }
    New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
    Rotate-Logs
    $config = Import-Clixml -LiteralPath $ConfigPath
    foreach ($name in 'HorusDbHost','HorusDbPort','HorusDbName','HorusDbUser','VpsApiUrl','ManagementId','LookbackDays') {
        if ([string]::IsNullOrWhiteSpace([string]$config.$name)) { throw "Configuração incompleta: $name" }
    }
    $env:HORUS_DB_HOST = $config.HorusDbHost
    $env:HORUS_DB_PORT = [string]$config.HorusDbPort
    $env:HORUS_DB_NAME = $config.HorusDbName
    $env:HORUS_DB_USER = $config.HorusDbUser
    $env:HORUS_DB_PASSWORD = [System.Net.NetworkCredential]::new('', $config.HorusDbPassword).Password
    $env:VPS_API_URL = $config.VpsApiUrl
    $env:VPS_SYNC_TOKEN = [System.Net.NetworkCredential]::new('', $config.VpsSyncToken).Password
    $env:HORUS_LEI_SECA_MANAGEMENT_ID = [string]$config.ManagementId
    $env:HORUS_BDT_LOOKBACK_DAYS = [string]$config.LookbackDays
    $env:HORUS_SYNC_STATE_FILE = $StatePath

    Push-Location $ProjectRoot
    try {
        if (!$ManagementIds -or ($ManagementIds | Where-Object { $_ -lt 1 })) {
            throw 'Informe IDs de gestão maiores que zero.'
        }
        $failures = @()
        foreach ($management in ($ManagementIds | Select-Object -Unique)) {
            $managementState = if ($management -eq 49) { $StatePath } else {
                Join-Path $DataRoot "horus-bdts-state.management-$management.json"
            }
            $arguments = @('manage.py', 'sync_horus_bdt', '--limit', $Limit,
                '--management-id', $management, '--state-file', $managementState)
            if ($DryRun) { $arguments += '--dry-run' }
            Write-SyncLog "Início gestão=$management (limite=$Limit; dry-run=$($DryRun.IsPresent))."
            & $PythonExe @arguments *>> $LogPath
            if ($LASTEXITCODE -ne 0) {
                $failures += $management
                Write-SyncLog "FALHA gestão=${management}: agente encerrou com código $LASTEXITCODE."
            } else {
                Write-SyncLog "Conclusão com sucesso gestão=$management."
            }
        }
        if ($failures.Count -gt 0) {
            throw "Falha nas gestões: $($failures -join ', ')."
        }
    } finally { Pop-Location }
    exit 0
} catch {
    if (!(Test-Path -LiteralPath $LogDirectory)) { New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null }
    Write-SyncLog "FALHA: $($_.Exception.Message)"
    exit 1
}

