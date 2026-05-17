param(
    [string]$ApiBaseUrl = "http://localhost:8000",
    [string]$Token = $env:TROTTER_AUTH_TOKEN,
    [string]$LinksPath = "$PSScriptRoot\instagram_batch_links.txt",
    [switch]$Batch,
    [switch]$ParseOnly
)

[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
try { chcp 65001 | Out-Null } catch {}

if (-not $Token) {
    Write-Error "Pass -Token or set TROTTER_AUTH_TOKEN."
    exit 1
}

if (-not (Test-Path -LiteralPath $LinksPath)) {
    Write-Error "Links file not found: $LinksPath"
    exit 1
}

$links = Get-Content -LiteralPath $LinksPath |
    ForEach-Object { $_.Trim() } |
    Where-Object { $_ -and -not $_.StartsWith("#") }

if (-not $links) {
    Write-Error "No links found in $LinksPath"
    exit 1
}

if ($Batch -and $ParseOnly) {
    $body = @{ source_urls = @($links) } | ConvertTo-Json -Depth 4
    Invoke-RestMethod `
        -Method Post `
        -Uri "$ApiBaseUrl/parse-travel-caption/batch" `
        -Headers @{ Authorization = "Bearer $Token" } `
        -ContentType "application/json" `
        -Body $body
    exit 0
}

if (-not $ParseOnly) {
    $body = @{ source_urls = @($links) } | ConvertTo-Json -Depth 4
    $result = Invoke-RestMethod `
        -Method Post `
        -Uri "$ApiBaseUrl/dreams/import-instagram-batch" `
        -Headers @{ Authorization = "Bearer $Token" } `
        -ContentType "application/json" `
        -Body $body

    $result.results | ForEach-Object {
        $place = if ($_.place_name) { $_.place_name } else { "(no place)" }
        $location = @($_.region, $_.city, $_.country) | Where-Object { $_ }
        $locationText = if ($location.Count) { $location -join ", " } else { "unknown location" }
        $maps = if ($_.google_maps_url) { " maps" } else { "" }
        $review = if ($_.needs_review) { "needs review" } else { "saved" }
        Write-Host "[$($_.dream_item_id)] $place - $locationText - $review$maps" -ForegroundColor Green
        if ($_.note) { Write-Host "  Note: $($_.note)" -ForegroundColor DarkYellow }
    }

    Write-Host ""
    Write-Host "Imported $($result.imported), duplicates $($result.duplicates), total $($result.total)." -ForegroundColor Cyan
    $outPath = Join-Path $PSScriptRoot "instagram_batch_import_results.json"
    $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $outPath -Encoding utf8
    Write-Host "Wrote $outPath" -ForegroundColor Cyan
    exit 0
}

$results = @()
$total = $links.Count
for ($i = 0; $i -lt $total; $i++) {
    $link = $links[$i]
    Write-Host ""
    Write-Host "[$($i + 1)/$total] Parsing $link" -ForegroundColor Cyan

    try {
        $body = @{ source_url = $link } | ConvertTo-Json -Depth 4
        $result = Invoke-RestMethod `
            -Method Post `
            -Uri "$ApiBaseUrl/parse-travel-caption" `
            -Headers @{ Authorization = "Bearer $Token" } `
            -ContentType "application/json" `
            -Body $body

        $first = $result.items | Select-Object -First 1
        $place = if ($first.place_name) { $first.place_name } else { "(no place)" }
        $location = @($first.city, $first.country) | Where-Object { $_ }
        $locationText = if ($location.Count) { $location -join ", " } else { "unknown location" }
        $review = if ($first.needs_review) { "needs review" } else { "parsed" }
        $parserError = if ($result.raw -and $result.raw.parser_error) { $result.raw.parser_error } else { $null }

        Write-Host "  OK: $place - $locationText - $review - confidence $($first.confidence)" -ForegroundColor Green
        if ($parserError) {
            Write-Host "  Note: $parserError" -ForegroundColor DarkYellow
        }
        $results += [pscustomobject]@{
            source_url = $link
            ok = $true
            place_name = $first.place_name
            city = $first.city
            country = $first.country
            category = $first.category
            confidence = $first.confidence
            needs_review = $first.needs_review
            note = $parserError
        }
    }
    catch {
        $message = $_.Exception.Message
        if ($_.ErrorDetails.Message) {
            $message = $_.ErrorDetails.Message
        }
        Write-Host "  FAILED: $message" -ForegroundColor Yellow
        $results += [pscustomobject]@{
            source_url = $link
            ok = $false
            error = $message
        }
    }
}

Write-Host ""
Write-Host "Done. $($results.Where({ $_.ok }).Count)/$total succeeded." -ForegroundColor Cyan
$results | Format-Table -AutoSize

$outPath = Join-Path $PSScriptRoot "instagram_batch_results.json"
$results | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $outPath -Encoding utf8
Write-Host "Wrote $outPath" -ForegroundColor Cyan
