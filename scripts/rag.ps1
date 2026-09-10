$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

function Test-PythonExecutable {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }
    if ($Path -like "*\Microsoft\WindowsApps\*") {
        return $false
    }

    try {
        & $Path --version *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

$PythonExe = $null
if (Test-PythonExecutable -Path $VenvPython) {
    $PythonExe = $VenvPython
}
else {
    $Candidates = @()
    $Candidates += Get-ChildItem -LiteralPath "$env:LOCALAPPDATA\Programs\Python" -Recurse -Depth 2 -Filter python.exe -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty FullName
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($PythonCommand) {
        $Candidates += $PythonCommand.Source
    }

    foreach ($Candidate in $Candidates | Select-Object -Unique) {
        if (Test-PythonExecutable -Path $Candidate) {
            $PythonExe = $Candidate
            break
        }
    }
}

if (-not $PythonExe) {
    Write-Error "No usable project Python was found. Run powershell -ExecutionPolicy Bypass -File scripts/setup.ps1 to initialize .venv. The Microsoft Store WindowsApps alias is intentionally ignored."
}

Push-Location -LiteralPath $ProjectRoot
try {
    & $PythonExe -m rag_app @args
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
