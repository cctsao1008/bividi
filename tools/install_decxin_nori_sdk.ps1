param(
    [string]$Archive = "",

    [string]$Destination = (Join-Path $PSScriptRoot "..\third_party\decxin-nori-sdk\sdk"),

    [switch]$AllowUnknownHash,

    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$KnownFullArchiveSha256 = "a603d88975c222a2891ca74c8c339509da755c279c0501f87e1c5a10df30c2f4"
$KnownBundledArchiveSha256 = "ff358cd7327f3246f9d5fcf58207bf1db46c384f4095b267c1d142d9fbc7daa5"
$BundlePrefix = Join-Path $PSScriptRoot "..\third_party\decxin-nori-sdk\vendor\DECXIN_Nori_Windows_x64_vendor_bundle.zip"
$temporaryArchive = $null

if ([string]::IsNullOrWhiteSpace($Archive)) {
    $expectedPartNames = 0..4 | ForEach-Object {
        "DECXIN_Nori_Windows_x64_vendor_bundle.zip.b64.part{0:D2}" -f $_
    }

    $bundleParts = @(
        Get-ChildItem -Path "$BundlePrefix.b64.part*" -File -ErrorAction SilentlyContinue |
            Sort-Object Name
    )

    $actualPartNames = @($bundleParts | ForEach-Object { $_.Name })
    if ($actualPartNames.Count -ne $expectedPartNames.Count -or
        (Compare-Object -ReferenceObject $expectedPartNames -DifferenceObject $actualPartNames)) {
        throw "Tracked DECXIN/Nori vendor bundle parts are incomplete. Expected: $($expectedPartNames -join ', '). Pull main again."
    }

    $encoded = [string]::Concat(@(
        $bundleParts | ForEach-Object { (Get-Content -Raw -Path $_.FullName).Trim() }
    ))

    try {
        $bundleBytes = [Convert]::FromBase64String($encoded)
    } catch {
        throw "Tracked DECXIN/Nori vendor bundle base64 is invalid: $($_.Exception.Message)"
    }

    $temporaryArchive = Join-Path ([System.IO.Path]::GetTempPath()) ("bividi-decxin-nori-sdk-{0}.zip" -f $PID)
    [System.IO.File]::WriteAllBytes($temporaryArchive, $bundleBytes)

    $archivePath = $temporaryArchive
    $expectedHash = $KnownBundledArchiveSha256
    $archiveKind = "tracked Windows x64 vendor bundle"
} else {
    $archivePath = (Resolve-Path $Archive).Path
    $expectedHash = $KnownFullArchiveSha256
    $archiveKind = "external vendor archive"
}

$destinationPath = [System.IO.Path]::GetFullPath($Destination)

try {
    $actualHash = (Get-FileHash -Algorithm SHA256 -Path $archivePath).Hash.ToLowerInvariant()

    Write-Host "DECXIN/Nori SDK source: $archiveKind"
    Write-Host "Archive: $archivePath"
    Write-Host "SHA-256: $actualHash"

    if ($actualHash -ne $expectedHash) {
        if (-not $AllowUnknownHash) {
            throw "Unknown DECXIN/Nori SDK archive hash. Expected $expectedHash. Re-run with -AllowUnknownHash only after intentionally accepting this vendor revision."
        }
        Write-Warning "Archive hash does not match the known package. Continuing because -AllowUnknownHash was supplied."
    }

    if (Test-Path $destinationPath) {
        $entries = @(Get-ChildItem -Force -Path $destinationPath -ErrorAction SilentlyContinue)
        if ($entries.Count -gt 0) {
            if (-not $Force) {
                throw "Destination is not empty: $destinationPath. Use -Force to replace the existing expanded SDK payload."
            }
            Remove-Item -Recurse -Force -Path $destinationPath
        }
    }

    New-Item -ItemType Directory -Force -Path $destinationPath | Out-Null
    Expand-Archive -Path $archivePath -DestinationPath $destinationPath -Force
} finally {
    if ($null -ne $temporaryArchive -and (Test-Path $temporaryArchive)) {
        Remove-Item -Force -Path $temporaryArchive
    }
}

$required = @(
    "Includes\Nori_Xvision_API\Nori_Xvision_API.h",
    "Includes\Nori_Xvision_API\Nori_Xvision_FirmwareControl.h",
    "Includes\Public\Nori_public.h",
    "Includes\Public\Nori_Error_Define.h",
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
Write-Host "Stage runtime DLL:"
Write-Host "  Copy-Item '$destinationPath\Libraries\win64\Nori_Xvision_API_x64.dll' '.\build-nori\Release\' -Force"
Write-Host ""
Write-Host "Probe with:"
Write-Host "  .\build-nori\Release\bividi-nori-probe.exe"
