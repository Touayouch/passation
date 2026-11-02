# Lance Passation sur ce PC. Utilisation : .\lancer.ps1
if (-not $env:COMINTY_API_KEY -or -not $env:COMINTY_USER_ID) {
  Write-Host "Definis d'abord COMINTY_API_KEY et COMINTY_USER_ID dans cette fenetre."
  exit 1
}
python -m pip install -q -r requirements.txt
Write-Host "Ouvre http://localhost:8000"
python -m uvicorn main:app --port 8000 --reload
