param(
    [Parameter(Mandatory=$true)][string]$ReportJson,
    [string]$Month = '2026-10',
    [string]$MySqlBin = 'D:\mysql-8.0.36-winx64\bin',
    [string]$DbHost = '127.0.0.1',
    [int]$Port = 3306,
    [string]$DbUser = 'root',
    [string]$Database = 'quality_assessment',
    [string]$OutputFile
)
$ErrorActionPreference = 'Stop'
$report = Get-Content -LiteralPath $ReportJson -Raw -Encoding UTF8 | ConvertFrom-Json
if ($Month -notmatch '^\d{4}-(0[1-9]|1[0-2])$' -or $report.end_month -ne $Month) {
    throw "Month mismatch: requested $Month, report ends $($report.end_month)"
}
$province = $report.metric_run_id
$city = $report.city_run_id
if ($province -cnotmatch '^metric_[0-9]{8}_[0-9]{6}_[0-9a-f]{8}$' -or $city -cnotmatch '^city_[0-9a-f]{32}$') {
    throw 'Expected both province and city run IDs in the report JSON.'
}
if (-not $OutputFile) { $OutputFile = Join-Path $PSScriptRoot "dedicated_line_province_city_$Month.sql" }
$OutputFile = [IO.Path]::GetFullPath($OutputFile)
if ([IO.File]::Exists($OutputFile)) { throw "Output already exists: $OutputFile" }
$dump = Join-Path $MySqlBin 'mysqldump.exe'
$stage = "$OutputFile.$([Guid]::NewGuid().ToString('N')).tmp"
$ready = "$stage.sql"
$tables = @('metric_run','result_orchestration_opening','result_orchestration_city')
$encoding = New-Object System.Text.UTF8Encoding($false)
try {
    $argsDump = @('--default-character-set=utf8mb4',"--host=$DbHost","--port=$Port","--user=$DbUser",'-p',
        '--single-transaction','--quick','--no-tablespaces','--set-gtid-purged=OFF',
        '--skip-add-drop-table','--skip-add-locks','--skip-disable-keys','--skip-triggers',
        '--complete-insert','--hex-blob',"--where=metric_run_id IN ('$province','$city')","--result-file=$stage",$Database) + $tables
    & $dump @argsDump
    if ($LASTEXITCODE -ne 0) { throw "mysqldump failed: $LASTEXITCODE" }
    $seen = @{}
    $reader = [IO.File]::OpenText($stage)
    try {
        $writer = New-Object System.IO.StreamWriter($ready,$false,$encoding)
        try {
            while ($null -ne ($line = $reader.ReadLine())) {
                if ($line -match '^INSERT INTO `([A-Za-z0-9_]+)`') {
                    $table = $Matches[1]
                    foreach ($id in @($province,$city)) {
                        if ($line.Contains("'$id'")) { $seen["$table/$id"] = $true }
                    }
                }
                $writer.WriteLine(($line -replace '^CREATE TABLE `','CREATE TABLE IF NOT EXISTS `'))
            }
        } finally { $writer.Dispose() }
    } finally { $reader.Dispose() }
    foreach ($key in @("metric_run/$province","metric_run/$city","result_orchestration_opening/$province","result_orchestration_city/$city")) {
        if (-not $seen.ContainsKey($key)) { throw "No rows for $key in dump; verify the database and run IDs." }
    }
    [IO.File]::Move($ready,$OutputFile)
    Write-Host "Province: $province"
    Write-Host "City:     $city"
    Write-Host "Exported: $OutputFile"
} finally {
    foreach ($path in @($stage,$ready)) { if ([IO.File]::Exists($path)) { [IO.File]::Delete($path) } }
}
