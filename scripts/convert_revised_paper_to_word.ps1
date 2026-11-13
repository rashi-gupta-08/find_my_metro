$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$sourcePdf = Join-Path $projectRoot 'output\pdf\FindMyMetro_Revised_Research_Paper.pdf'
$outputDir = Join-Path $projectRoot 'output\docx'
$renderDir = Join-Path $projectRoot 'tmp\docx\revised-paper'
New-Item -ItemType Directory -Force -Path $outputDir, $renderDir | Out-Null
$outputDocx = Join-Path $outputDir 'FindMyMetro_Revised_Research_Paper.docx'
$renderPdf = Join-Path $renderDir 'word-render.pdf'
$wordApp = $null
$paperDoc = $null
try {
    $wordApp = New-Object -ComObject Word.Application
    $wordApp.Visible = $true
    $wordApp.DisplayAlerts = 0
    $wordApp.AutomationSecurity = 3
    $wordApp.ScreenUpdating = $false
    Write-Output 'Converting the revised PDF with Word PDF Reflow.'
    $paperDoc = $wordApp.Documents.Open($sourcePdf, $false, $false, $false)
    $paperDoc.TrackRevisions = $false
    $paperDoc.Repaginate()
    $paperDoc.SaveAs2($outputDocx, 16)
    Write-Output ('Word document saved. Pages: ' + $paperDoc.ComputeStatistics(2))
    $paperDoc.ExportAsFixedFormat($renderPdf, 17)
    Write-Output ('Preview saved: ' + $renderPdf)
} finally {
    if ($null -ne $paperDoc) {
        $paperDoc.Close(0)
        [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($paperDoc)
    }
    if ($null -ne $wordApp) {
        $wordApp.Quit(0)
        [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($wordApp)
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
