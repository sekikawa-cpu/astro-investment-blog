# git-sync.ps1
# 使い方: .\git-sync.ps1 "コミットメッセージ"

param(
    [string]$message = "update"
)

Write-Host "==> 変更を一時退避..." -ForegroundColor Cyan
git stash

Write-Host "==> リモートの変更を取り込み中..." -ForegroundColor Cyan
git pull --rebase origin main

if ($LASTEXITCODE -ne 0) {
    Write-Host "エラー: rebase に失敗しました。コンフリクトを確認してください。" -ForegroundColor Red
    exit 1
}

Write-Host "==> 退避した変更を戻し中..." -ForegroundColor Cyan
git stash pop

Write-Host "==> 変更をコミット中: '$message'" -ForegroundColor Cyan
git add .
git commit -m $message

Write-Host "==> プッシュ中..." -ForegroundColor Cyan
git push origin main

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ 完了！正常にプッシュされました。" -ForegroundColor Green
} else {
    Write-Host "エラー: プッシュに失敗しました。" -ForegroundColor Red
}
