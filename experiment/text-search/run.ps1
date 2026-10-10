param([ValidateSet('start','build','evaluate','status','stop')][string]$Action='start')
$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
$env:CONTAINER_CONNECTION='embeddinggemma2-lab-root'
$env:PODMAN_COMPOSE_PROVIDER=(Get-Command podman-compose -ErrorAction Stop).Source
$connection='embeddinggemma2-lab-root'
switch($Action){
  'build' { podman --connection $connection compose build }
  'start' {
    $machine=podman machine inspect embeddinggemma2-lab | ConvertFrom-Json
    if($LASTEXITCODE -ne 0){throw '専用マシンがありません。README.mdの初回セットアップを参照してください。'}
    if($machine.State -ne 'running'){podman machine start embeddinggemma2-lab;if($LASTEXITCODE -ne 0){throw 'Podmanマシンの起動に失敗しました。'}}
    podman --connection $connection compose up -d --build
  }
  'evaluate' { podman --connection $connection compose exec -T search python evaluate.py }
  'status' { podman --connection $connection compose ps }
  'stop' { podman --connection $connection compose down }
}
if($LASTEXITCODE -ne 0){throw "Podman Compose失敗: exit=$LASTEXITCODE"}
