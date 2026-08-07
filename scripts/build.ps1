$originalLocation = Get-Location
Set-Location $PSScriptRoot

Write-Host -NoNewline 'Building executable...'
$stderrFile = [System.IO.Path]::GetTempFileName()
uv run pyinstaller --onefile --windowed --collect-data spellchecker ../src/morgul/__main__.py > $null 2> $stderrFile
$exitCode = $LASTEXITCODE
if ($exitCode -eq 0) {
    Write-Host ' done'

    Remove-Item ../morgul.exe -ErrorAction SilentlyContinue
    Move-Item ./dist/__main__.exe ../morgul.exe
    $ExecutableLocation = Resolve-Path "../morgul.exe"
    Write-Host "Moved executable to $ExecutableLocation"
} else {
    Write-Host 'failed'
    Get-Content $stderrFile
}
Remove-Item $stderrFile


$artifacts =  './__main__.spec', './build/', './dist/'
if ($artifacts | Where-Object { Test-Path $_ }) {
    Write-Host -NoNewline 'Cleaning up artifacts...'
    foreach ($artifact in $artifacts) {
        if (Test-Path $artifact) {
            Remove-Item -Recurse -Force $artifact
        }
    }
    Write-Host ' done'
}

Set-Location $originalLocation