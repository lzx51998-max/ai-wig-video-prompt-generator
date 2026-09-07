$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

$PythonCandidates = @()
$PythonCandidates += Get-ChildItem -LiteralPath "$env:LOCALAPPDATA\Programs\Python" -Recurse -Depth 2 -Filter python.exe -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty FullName
$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($PythonCommand) {
    $PythonCandidates += $PythonCommand.Source
}
$PythonExe = $null
foreach ($Candidate in $PythonCandidates | Select-Object -Unique) {
    & $Candidate --version *> $null
    if ($LASTEXITCODE -eq 0) {
        $PythonExe = $Candidate
        break
    }
}
if (-not $PythonExe) {
    Write-Error "未找到 Python。请安装 Python 3.11 或更高版本，并勾选 Add Python to PATH。"
}

$VersionText = & $PythonExe --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "Windows 当前的 python 命令不可用。请从 python.org 安装 Python 3.11 或更高版本。"
}
Write-Host $VersionText
$VersionCode = & $PythonExe -c "import sys; print(sys.version_info.major * 100 + sys.version_info.minor)"
if ([int]$VersionCode -lt 311) {
    Write-Error "Python 版本过低，需要 Python 3.11 或更高版本。"
}

if (-not (Test-Path -LiteralPath ".venv")) {
    & $PythonExe -m venv .venv
}

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -e .

$OllamaExe = $null
$OllamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
if ($OllamaCommand) {
    $OllamaExe = $OllamaCommand.Source
}
$LocalOllama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
if ((-not $OllamaExe) -and (Test-Path -LiteralPath $LocalOllama)) {
    $OllamaExe = $LocalOllama
}
if (-not $OllamaExe) {
    Write-Error "未找到 Ollama。请先从 https://ollama.com/download/windows 安装并启动 Ollama，然后重新运行初始化。"
}

& $OllamaExe pull embeddinggemma
& $VenvPython -m rag_app index
& $VenvPython -m rag_app doctor

Write-Host "提示词工作台初始化完成。现在可以回到 Codex 对话中直接要求生成提示词。" -ForegroundColor Green
