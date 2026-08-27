# Release helper: copies the built exe and prints SHA256.
# Run AFTER a successful PyInstaller build. Does NOT rebuild the app.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$src = Join-Path $root "dist\BiliDownloader.exe"
$rel = Join-Path $root "github-release\release"
if (-not (Test-Path $src)) {
    Write-Output "ERROR: dist\BiliDownloader.exe not found. Build it first via build.bat."
    exit 1
}
New-Item -ItemType Directory -Path $rel -Force | Out-Null
Copy-Item $src (Join-Path $rel "BiliDownloader.exe") -Force
$exe = Get-Item (Join-Path $rel "BiliDownloader.exe")
Write-Output ("Copied: " + $exe.FullName)
Write-Output ("Size:   " + [math]::Round($exe.Length / 1MB, 1) + " MB")
Write-Output ("SHA256: " + (Get-FileHash $exe.FullName -Algorithm SHA256).Hash)
Write-Output "Upload this file as a GitHub Release asset."