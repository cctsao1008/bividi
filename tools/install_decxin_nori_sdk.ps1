param(
    [Parameter(Mandatory = $true)]
    [string]$Archive,

    [string]$Destination = (Join-Path $PSScriptRoot "..\third_party\decxin-nori-sdk\sdk"),

    [switch]$AllowUnknownHash,

    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$KnownArchiveSha256 = "a603d88975c222a2891ca74c8c339509da755c279c0501f87e1c5a10df30c2f4"

$archivePath = (Resolve-Path $Archive).Path
$destinationPath = [System.IO.Path]::GetFullPath($Destination)

$actualHash = (Get-FileHash -Algorithm SHA256 -Path $archivePath).Hash.ToLowerInvariant()
Write-Host "DECXIN/Nori SDK archive: $archivePath"
Write-Host "SHA-256: $actualHash"

if ($actualHash -ne $KnownArchiveSha256) {
    if (-not $AllowUnknownHash) {
        throw "Unknown DECXIN/Nori SDK archive hash. Expected $KnownArchiveSha256. Re-run with -AllowUnknownHash only after intentionally accepting this vendor revision."
    }
    Write-Warning "Archive hash does not match the known AR0234 Windows SDK package. Continuing because -AllowUnknownHash was supplied."
}

if (Test-Path $destinationPath) {
    $entries = @(Get-ChildItem -Force -Path $destinationPath -ErrorAction SilentlyContinue)
    if ($entries.Count -gt 0) {
        if (-not $Force) {
            throw "Destination is not empty: $destinationPath. Use -Force to replace the existing local SDK payload."
        }
        Remove-Item -Recurse -Force -Path $destinationPath
    }
}

New-Item -ItemType Directory -Force -Path $destinationPath | Out-Null
Expand-Archive -Path $archivePath -DestinationPath $destinationPath -Force

$required = @(
    "Includes\Nori_Xvision_API\Nori_Xvision_API.h",
    "Libraries\win64\Nori_Xvision_API_x64.lib",
    "Libraries\win64\Nori_Xvision_API_x64.dll",
    "Samples\C++\x64\Release\Grab_Image.exe"
)

$missing = @()
foreach ($relative in $required) {
    $candidate = Join-Path $destinationPath $relative
    if (-not (Test-Path $candidate)) {
        $missing += $relative
    }
}

if ($missing.Count -gt 0) {
    throw "SDK extraction completed but required files are missing:`n - $($missing -join "`n - ")"
}

Write-Host ""
Write-Host "DECXIN/Nori SDK validation: PASS"
Write-Host "SDK root: $destinationPath"
Write-Host ""
Write-Host "Build with:"
Write-Host "  `$SdkRoot = '$destinationPath'"
Write-Host '  cmake -S . -B build-nori -DBIVIDI_WITH_NORI_SDK=ON -DBIVIDI_NORI_SDK_ROOT="$SdkRoot"'
Write-Host "  cmake --build build-nori --config Release"
Write-Host ""
Write-Host "Before running on Windows, stage the vendor runtime DLL:"
Write-Host "  Copy-Item '$destinationPath\Libraries\win64\Nori_Xvision_API_x64.dll' '.\build-nori\Release\'"
Write-Host ""
Write-Host "Probe with:"
Write-Host "  .\build-nori\Release\bividi-nori-probe.exe"
