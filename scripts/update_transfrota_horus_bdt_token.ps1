[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$DataRoot = 'C:\ProgramData\Transfrota'
$ConfigPath = Join-Path $DataRoot 'horus-bdts.config.clixml'
$TemporaryConfigPath = "$ConfigPath.tmp"

if (!(Test-Path -LiteralPath $ConfigPath)) {
    throw "Configuração DPAPI não encontrada: $ConfigPath"
}

# The replacement secret is never sent to stdout, command history, task XML,
# or the repository. This script deliberately does not enable the task.
$newToken = Read-Host 'Novo token VPS_SYNC_TOKEN/FLEET_SYNC_TOKEN' -AsSecureString
if ($newToken.Length -eq 0) { throw 'O novo token é obrigatório.' }

$config = Import-Clixml -LiteralPath $ConfigPath
$config.VpsSyncToken = $newToken
$config | Export-Clixml -LiteralPath $TemporaryConfigPath -Force
Move-Item -LiteralPath $TemporaryConfigPath -Destination $ConfigPath -Force
Write-Host 'Token DPAPI atualizado. A tarefa permanece no estado atual.'
