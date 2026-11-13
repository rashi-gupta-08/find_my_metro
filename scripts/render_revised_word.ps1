$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$sourceDocx = Join-Path $projectRoot 'output\docx\FindMyMetro_Revised_Research_Paper.docx'
$renderPdf = Join-Path $projectRoot 'tmp\docx\revised-paper\final-word-render.pdf'
$wordApp = $null
$paperDoc = $null
try {
    $wordApp = New-Object -ComObject Word.Application
    $wordApp.Visible = $false
    $wordApp.DisplayAlerts = 0
    $wordApp.AutomationSecurity = 3
    Write-Output 'Opening the final Word document for layout verification.'
    $paperDoc = $wordApp.Documents.Open($sourceDocx, $false, $true, $false)
    $paperDoc.ExportAsFixedFormat($renderPdf, 17)
    Write-Output ('Rendered pages: ' + $paperDoc.ComputeStatistics(2))
    Write-Output $renderPdf
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
