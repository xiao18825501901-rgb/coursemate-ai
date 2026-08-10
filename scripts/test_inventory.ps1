$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$workRoot = Join-Path $projectRoot "work"
$testRoot = Join-Path $workRoot ("inventory-test-" + [guid]::NewGuid().ToString("N"))
$inventoryScript = Join-Path $PSScriptRoot "inventory.ps1"
$jsonPath = Join-Path $testRoot "inventory.json"
$csvPath = Join-Path $testRoot "inventory.csv"

New-Item -ItemType Directory -Force -Path $testRoot | Out-Null

try {
    & $inventoryScript -OutputJson $jsonPath -OutputCsv $csvPath

    $inventory = Get-Content -Raw -Encoding UTF8 -LiteralPath $jsonPath | ConvertFrom-Json
    $files = @($inventory.files)
    $sources = @($inventory.sources)

    if ($files.Count -ne 86) {
        throw "Expected 86 files, found $($files.Count)."
    }

    $csCount = @($files | Where-Object courseId -eq "cs3481").Count
    $geCount = @($files | Where-Object courseId -eq "ge2324").Count
    if ($csCount -ne 50 -or $geCount -ne 36) {
        throw "Expected course counts cs3481=50 and ge2324=36, found $csCount and $geCount."
    }

    $downloadsRoot = "D:\" + [string][char]0x4E0B + [string][char]0x8F7D
    $expectedTut7 = Join-Path $downloadsRoot "tut7"
    $expectedTut8 = Join-Path $downloadsRoot "tut8"
    $missing = @($sources | Where-Object exists -eq $false | Select-Object -ExpandProperty sourcePath)
    if ($missing.Count -ne 2 -or $missing -notcontains $expectedTut7 -or $missing -notcontains $expectedTut8) {
        throw "Missing-source records do not match tut7 and tut8."
    }

    if (-not (Test-Path -LiteralPath $csvPath)) {
        throw "CSV inventory was not created."
    }

    $csvRows = @(Import-Csv -LiteralPath $csvPath -Encoding UTF8)
    if ($csvRows.Count -ne 86) {
        throw "Expected 86 CSV rows, found $($csvRows.Count)."
    }
    if (@($csvRows | Where-Object { -not $_.courseId -or -not $_.fullPath }).Count -ne 0) {
        throw "CSV rows contain empty courseId or fullPath values."
    }
    $missingFiles = @($files | Where-Object { -not (Test-Path -LiteralPath $_.fullPath -PathType Leaf) })
    if ($missingFiles.Count -ne 0) {
        throw "JSON inventory contains $($missingFiles.Count) fullPath values that cannot be read back."
    }
    $missingCsvFiles = @($csvRows | Where-Object { -not (Test-Path -LiteralPath $_.fullPath -PathType Leaf) })
    if ($missingCsvFiles.Count -ne 0) {
        throw "CSV inventory contains $($missingCsvFiles.Count) fullPath values that cannot be read back."
    }

    Write-Output "PASS inventory: 86 files (cs3481=50, ge2324=36), 2 missing sources recorded."
}
finally {
    $resolvedTestRoot = [IO.Path]::GetFullPath($testRoot)
    $resolvedWorkRoot = [IO.Path]::GetFullPath($workRoot) + [IO.Path]::DirectorySeparatorChar
    if ($resolvedTestRoot.StartsWith($resolvedWorkRoot, [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
