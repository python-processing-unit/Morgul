Set-Location $PSScriptRoot

Write-Host -NoNewline 'Building executable...'
uv run pyinstaller --onefile --windowed ./src/morgul/__main__.py *> $null
Write-Host ' done'

Remove-Item ./morgul.exe
Move-Item ./dist/__main__.exe ./morgul.exe
$ExecutableLocation = "$PSScriptRoot" + '\morgul.exe'
Write-Host "Moved executable to $ExecutableLocation"

Write-Host -NoNewline 'Cleaning up artifacts...'
Remove-Item ./__main__.spec
Remove-Item -Recurse ./build/
Remove-Item -Recurse ./dist/
Write-Host ' done'