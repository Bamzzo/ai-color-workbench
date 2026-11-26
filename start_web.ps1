$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
  Write-Host "未找到 .venv，请先在项目根目录创建虚拟环境并安装依赖。" -ForegroundColor Yellow
  exit 1
}

$Frontend = Join-Path $Root "frontend"
if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
  Push-Location $Frontend
  npm install
  Pop-Location
}

$BackendPort = 8765
$ProbeUrl = "http://127.0.0.1:$BackendPort/api/presets"

Write-Host "启动 FastAPI ($BackendPort) 与 Vite 前端 (5173)…" -ForegroundColor Cyan

# 后端已经在跑就不再重复启动（多开会抢端口）
$alreadyListening = $false
try {
  $probe = Invoke-WebRequest -UseBasicParsing $ProbeUrl -TimeoutSec 2
  $alreadyListening = $probe.StatusCode -eq 200
} catch {
  $alreadyListening = $false
}

if ($alreadyListening) {
  Write-Host "后端已在 $BackendPort 端口运行，跳过启动。" -ForegroundColor Yellow
} else {
  # 故意不加 --reload：演示时 media_store 会持续写入 runtime/cache，
  # 热重载会在上传/导出过程中重启进程，直接打断已加载的素材与导出任务。
  Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location '$Root'; & '$VenvPython' -m uvicorn api.server:app --host 127.0.0.1 --port $BackendPort"
  )

  # uvicorn 要先 import numpy/PIL 才会绑定端口，必须轮询到真正就绪，
  # 否则前端刚起来时的首个 /api 请求会被代理成 ECONNREFUSED。
  Write-Host "等待后端就绪…" -NoNewline -ForegroundColor Cyan
  $ready = $false
  for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    try {
      $probe = Invoke-WebRequest -UseBasicParsing $ProbeUrl -TimeoutSec 2
      if ($probe.StatusCode -eq 200) { $ready = $true; break }
    } catch {
      Write-Host "." -NoNewline
    }
  }

  if (-not $ready) {
    Write-Host ""
    Write-Host "后端 30 秒内未就绪，请检查后端窗口的报错（依赖或 .env 问题）。" -ForegroundColor Red
    Write-Host "前端仍会启动，但 /api 请求会失败。" -ForegroundColor Yellow
  } else {
    Write-Host " 就绪" -ForegroundColor Green
  }
}

Start-Process powershell -ArgumentList @(
  "-NoExit",
  "-Command",
  "Set-Location '$Frontend'; npm run dev"
)

Write-Host "已在独立窗口中启动后端与前端。" -ForegroundColor Green