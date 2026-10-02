[CmdletBinding()]
param(
    [switch]$DryRun,
    [int]$Limit = 100
)

$ErrorActionPreference = 'Stop'
$OutputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $OutputEncoding
$env:PYTHONIOENCODING = 'utf-8'
$ProjectRoot = 'D:\gestao_frotas'
$PythonExe = 'D:\gestao_frotas\.venv\Scripts\python.exe'
$DataRoot = 'C:\ProgramData\Transfrota'
$ConfigPath = Join-Path $DataRoot 'horus-bdts.config.clixml'
$StatePath = Join-Path $DataRoot 'horus-bdts-state.json'
$LogDirectory = Join-Path $DataRoot 'logs'
$LogPath = Join-Path $LogDirectory 'horus-bdts-sync.log'
$BootstrapLogPath = Join-Path $LogDirectory 'horus-bdts-bootstrap.log'

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
    New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
    Add-Content -LiteralPath $BootstrapLogPath -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ssK') runner iniciado." -Encoding utf8
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
        $arguments = @('manage.py', 'sync_horus_bdt', '--limit', $Limit)
        if ($DryRun) { $arguments += '--dry-run' }
        Write-SyncLog "Início (limite=$Limit; dry-run=$($DryRun.IsPresent))."
        & $PythonExe @arguments 2>&1 | ForEach-Object {
            Add-Content -LiteralPath $LogPath -Value $_ -Encoding utf8
        }
        $agentExitCode = $LASTEXITCODE
        if ($agentExitCode -ne 0) { throw "Agente encerrou com código $agentExitCode." }
        Write-SyncLog 'Conclusão com sucesso.'
    } finally { Pop-Location }
    exit 0
} catch {
    try {
        if (!(Test-Path -LiteralPath $LogDirectory)) { New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null }
        Add-Content -LiteralPath $BootstrapLogPath -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ssK') FALHA: $($_.Exception.Message)" -Encoding utf8
        Write-SyncLog "FALHA: $($_.Exception.Message)"
    } catch { }
    exit 1
}
