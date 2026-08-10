param(
    [string]$OutputJson = (Join-Path $PSScriptRoot "..\data\inventory\course-files.json"),
    [string]$OutputCsv = (Join-Path $PSScriptRoot "..\data\inventory\course-files.csv")
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$downloadsRoot = "D:\" + [string][char]0x4E0B + [string][char]0x8F7D
$sourceDefinitions = @(
    [ordered]@{ courseId = "cs3481"; sourcePath = (Join-Path $downloadsRoot "course_files_export (4)") },
    [ordered]@{ courseId = "cs3481"; sourcePath = (Join-Path $downloadsRoot "course_files_export (6)") },
    [ordered]@{ courseId = "cs3481"; sourcePath = (Join-Path $downloadsRoot "tut7") },
    [ordered]@{ courseId = "cs3481"; sourcePath = (Join-Path $downloadsRoot "tut8") },
    [ordered]@{ courseId = "ge2324"; sourcePath = (Join-Path $downloadsRoot "course_files_export (3)") },
    [ordered]@{ courseId = "ge2324"; sourcePath = (Join-Path $downloadsRoot "course_files_export (5)") }
)

function Get-ImporterMode {
    param([string]$Extension)

    switch ($Extension.ToLowerInvariant()) {
        ".pdf" { "index" }
        ".md" { "index" }
        ".markdown" { "index" }
        ".txt" { "index" }
        ".docx" { "index" }
        ".pptx" { "index" }
        ".ppt" { "optional-conversion" }
        default { "inventory-only" }
    }
}

$allFiles = [System.Collections.Generic.List[object]]::new()
$sources = [System.Collections.Generic.List[object]]::new()

foreach ($definition in $sourceDefinitions) {
    $sourcePath = $definition.sourcePath
    $exists = Test-Path -LiteralPath $sourcePath -PathType Container
    $sourceFiles = @()

    if ($exists) {
        $sourceFiles = @(
            Get-ChildItem -LiteralPath $sourcePath -File -Recurse -ErrorAction Stop |
                Sort-Object FullName
        )

        foreach ($file in $sourceFiles) {
            $relativePath = $file.FullName.Substring($sourcePath.Length).TrimStart("\")
            $extension = $file.Extension.ToLowerInvariant()
            $allFiles.Add([pscustomobject][ordered]@{
                courseId = $definition.courseId
                sourcePath = $sourcePath
                relativePath = $relativePath
                fullPath = $file.FullName
                filename = $file.Name
                extension = $extension
                sizeBytes = $file.Length
                lastWriteTimeUtc = $file.LastWriteTimeUtc.ToString("o")
                importerMode = Get-ImporterMode -Extension $extension
            })
        }
    }

    $extensionSummary = @(
        $sourceFiles |
            Group-Object { $_.Extension.ToLowerInvariant() } |
            Sort-Object Name |
            ForEach-Object {
                [ordered]@{
                    extension = if ($_.Name) { $_.Name } else { "[none]" }
                    count = $_.Count
                }
            }
    )

    $sources.Add([pscustomobject][ordered]@{
        courseId = $definition.courseId
        sourcePath = $sourcePath
        exists = $exists
        fileCount = $sourceFiles.Count
        totalBytes = [long](($sourceFiles | Measure-Object Length -Sum).Sum)
        extensions = $extensionSummary
    })
}

$inventory = [ordered]@{
    schemaVersion = 1
    sources = @($sources)
    files = @($allFiles | Sort-Object courseId, sourcePath, relativePath)
}

$jsonDirectory = Split-Path -Parent $OutputJson
$csvDirectory = Split-Path -Parent $OutputCsv
New-Item -ItemType Directory -Force -Path $jsonDirectory, $csvDirectory | Out-Null

$inventory | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath $OutputJson -Encoding UTF8
$inventory.files |
    Select-Object courseId, sourcePath, relativePath, fullPath, filename, extension, sizeBytes, lastWriteTimeUtc, importerMode |
    Export-Csv -LiteralPath $OutputCsv -NoTypeInformation -Encoding UTF8

Write-Output "Inventory written: $($inventory.files.Count) files across $($inventory.sources.Count) configured sources."
