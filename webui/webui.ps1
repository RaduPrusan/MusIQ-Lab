<#
.SYNOPSIS
  MusIQ-Lab webui Windows lifecycle helper.

.DESCRIPTION
  Verb-dispatched manager for `python -m webui`. Replaces the bash-only
  scripts in scripts/. Handles detached launch, PID + port tracking,
  log redirection, readiness polling, status, log tailing, and a console
  monitor.

.EXAMPLE
  .\webui.ps1 start
  .\webui.ps1 status
  .\webui.ps1 monitor
  .\webui.ps1 logs
  .\webui.ps1 logs -Err
  .\webui.ps1 logs -Both -Tail 50
  .\webui.ps1 logs -Static -Tail 200
  .\webui.ps1 stop
  .\webui.ps1 kill
  .\webui.ps1 restart
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('start','stop','restart','kill','status','logs','monitor','help')]
    [string]$Command = 'help',

    [switch]$Err,
    [switch]$Both,
    [switch]$Static,
    [int]$Tail = 20,
    [int]$Port = 8765,
    [int]$ReadyTimeoutSec = 30
)

$ErrorActionPreference = 'Stop'

# ---- Configuration -------------------------------------------------------

$WebuiDir   = $PSScriptRoot
$VenvPython = Join-Path $WebuiDir '.venv\Scripts\python.exe'
$LogFile    = Join-Path $WebuiDir 'webui.log'
$ErrFile    = Join-Path $WebuiDir 'webui.log.err'
$PidFile    = Join-Path $WebuiDir '.webui.pid'
$BindHost   = '127.0.0.1'
$ReadyUrl   = "http://${BindHost}:${Port}/api/tracks"
$RootUrl    = "http://${BindHost}:${Port}/"

# ---- Helpers -------------------------------------------------------------

function Get-PortOwner {
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Sort-Object OwningProcess -Unique
    if (-not $conn) { return $null }

    $procId = $conn[0].OwningProcess
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if (-not $proc) { return $null }

    $cim = Get-CimInstance Win32_Process -Filter "ProcessId = $procId" -ErrorAction SilentlyContinue
    $cmd = if ($cim) { $cim.CommandLine } else { '' }

    [PSCustomObject]@{
        Pid         = $proc.Id
        Name        = "$($proc.ProcessName).exe"
        StartTime   = $proc.StartTime
        CommandLine = $cmd
        IsWebui     = ($cmd -match '\bpython' -and $cmd -match '-m\s+webui')
    }
}

function Test-Responding {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri $ReadyUrl -TimeoutSec 2
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Get-AllWebuiProcs {
    @(Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match '-m\s+webui' })
}

function Get-RelatedTreePids {
    # Returns the set of PIDs in the same process tree as $AnchorPid:
    # the anchor itself, all ancestors (chain of ParentProcessId), and all
    # descendants (recursive children). Used to distinguish "this webui's
    # parent/child processes" from genuinely unrelated `-m webui` strays.
    param([int]$AnchorPid)
    if ($AnchorPid -le 0) { return @{} }

    $allProcs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $byPid = @{}
    foreach ($p in $allProcs) { $byPid[[int]$p.ProcessId] = $p }

    $related = @{ $AnchorPid = $true }

    # Walk up: ancestors
    $cur = $AnchorPid
    $hops = 0
    while ($byPid.ContainsKey($cur) -and $hops -lt 32) {
        $parent = [int]$byPid[$cur].ParentProcessId
        if ($parent -le 0 -or $related.ContainsKey($parent)) { break }
        $related[$parent] = $true
        $cur = $parent
        $hops++
    }

    # Walk down: descendants (BFS)
    $queue = New-Object System.Collections.Queue
    $queue.Enqueue($AnchorPid)
    while ($queue.Count -gt 0) {
        $head = [int]$queue.Dequeue()
        foreach ($p in $allProcs) {
            if ([int]$p.ParentProcessId -eq $head) {
                $cpid = [int]$p.ProcessId
                if (-not $related.ContainsKey($cpid)) {
                    $related[$cpid] = $true
                    $queue.Enqueue($cpid)
                }
            }
        }
    }

    return $related
}

function Get-Orphans {
    # Webui processes outside the port-owner's process tree. If no port
    # owner is given, every webui process is considered an orphan.
    param([int]$AnchorPid = 0)
    $all = Get-AllWebuiProcs
    if ($AnchorPid -le 0) { return $all }
    $tree = Get-RelatedTreePids -AnchorPid $AnchorPid
    return @($all | Where-Object { -not $tree.ContainsKey([int]$_.ProcessId) })
}

function Get-WebuiTreeMembers {
    # Webui processes inside the port-owner's tree (excluding the anchor
    # itself). Used by status to show "parent PID N" / "child PID N".
    param([int]$AnchorPid)
    if ($AnchorPid -le 0) { return @() }
    $tree = Get-RelatedTreePids -AnchorPid $AnchorPid
    Get-AllWebuiProcs | Where-Object {
        $tree.ContainsKey([int]$_.ProcessId) -and [int]$_.ProcessId -ne $AnchorPid
    }
}

function Wait-Ready {
    param([int]$TimeoutSec = 30)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-Responding) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Format-Bytes {
    param([long]$B)
    if ($B -lt 1KB) { return "$B B" }
    if ($B -lt 1MB) { return "{0:N1} KB" -f ($B / 1KB) }
    if ($B -lt 1GB) { return "{0:N1} MB" -f ($B / 1MB) }
    return "{0:N1} GB" -f ($B / 1GB)
}

# ---- Verbs ---------------------------------------------------------------

function Invoke-Start {
    if (-not (Test-Path $VenvPython)) {
        Write-Error "venv python not found: $VenvPython`nRun: cd webui; uv venv .venv; uv pip install -r requirements.txt"
        return
    }

    $owner = Get-PortOwner
    if ($owner) {
        if ($owner.IsWebui -and (Test-Responding)) {
            Write-Host "webui already running (PID $($owner.Pid)), responsive at $RootUrl" -ForegroundColor Green
            return
        }
        if ($owner.IsWebui) {
            Write-Warning "webui PID $($owner.Pid) holds port $Port but is not responding."
            Write-Host  "  hint: .\webui.ps1 kill  (then start again)"
            return
        }
        Write-Error "Port $Port held by foreign process: $($owner.Name) PID $($owner.Pid)`n  cmd: $($owner.CommandLine)"
        return
    }

    $proc = Start-Process -FilePath $VenvPython `
                          -ArgumentList '-m','webui' `
                          -WorkingDirectory $WebuiDir `
                          -WindowStyle Hidden `
                          -RedirectStandardOutput $LogFile `
                          -RedirectStandardError  $ErrFile `
                          -PassThru

    Set-Content -Path $PidFile -Value $proc.Id -Encoding ASCII

    Write-Host "starting webui (PID $($proc.Id))..." -NoNewline
    if (Wait-Ready -TimeoutSec $ReadyTimeoutSec) {
        Write-Host " ready at $RootUrl" -ForegroundColor Green
        Write-Host "  log:      $LogFile"
        Write-Host "  log.err:  $ErrFile"
        Write-Host "  pid file: $PidFile"
    } else {
        Write-Host ""
        Write-Warning "PID $($proc.Id) launched but did not become ready within ${ReadyTimeoutSec}s"
        if ((Test-Path $ErrFile) -and ((Get-Item $ErrFile).Length -gt 0)) {
            Write-Host "── tail of $ErrFile ──" -ForegroundColor Yellow
            Get-Content $ErrFile -Tail 20 -ErrorAction SilentlyContinue
        }
    }
}

function Invoke-Stop {
    param([switch]$Force)

    $stopped = $false
    $owner = Get-PortOwner

    if ($owner) {
        # Snapshot tree before killing -- members may exit on cascade
        $treeMembers = @(Get-WebuiTreeMembers -AnchorPid $owner.Pid)

        if ($Force) {
            Write-Host "killing PID $($owner.Pid) ($($owner.Name)) on port $Port (tree)"
            & taskkill.exe /F /T /PID $owner.Pid 2>$null | Out-Null
        } else {
            Write-Host "stopping PID $($owner.Pid) ($($owner.Name)) on port $Port..."
            & taskkill.exe /PID $owner.Pid /T 2>$null | Out-Null
            $deadline = (Get-Date).AddSeconds(3)
            while ((Get-Date) -lt $deadline) {
                if (-not (Get-Process -Id $owner.Pid -ErrorAction SilentlyContinue)) { break }
                Start-Sleep -Milliseconds 200
            }
            if (Get-Process -Id $owner.Pid -ErrorAction SilentlyContinue) {
                Write-Host "  graceful timeout, forcing tree" -ForegroundColor DarkYellow
                & taskkill.exe /F /T /PID $owner.Pid 2>$null | Out-Null
            }
        }

        # Clean up surviving tree members (parent supervisor that didn't
        # exit when its listener child died)
        Start-Sleep -Milliseconds 300
        foreach ($m in $treeMembers) {
            $mid = [int]$m.ProcessId
            if (Get-Process -Id $mid -ErrorAction SilentlyContinue) {
                Write-Host "  cleaning up tree member PID $mid"
                Stop-Process -Id $mid -Force -ErrorAction SilentlyContinue
            }
        }
        $stopped = $true
    }

    if ($Force) {
        # Sweep any unrelated -m webui leftovers (no anchor = all of them)
        $orphans = @(Get-Orphans -AnchorPid 0)
        foreach ($o in $orphans) {
            $oid = [int]$o.ProcessId
            if (Get-Process -Id $oid -ErrorAction SilentlyContinue) {
                Write-Host "killing orphan PID $oid ($($o.Name))"
                Stop-Process -Id $oid -Force -ErrorAction SilentlyContinue
                $stopped = $true
            }
        }
    }

    if (Test-Path $PidFile) { Remove-Item $PidFile -Force -ErrorAction SilentlyContinue }

    if ($stopped) { Write-Host "webui stopped" -ForegroundColor Green }
    else          { Write-Host "webui not running" -ForegroundColor DarkGray }
}

function Invoke-Restart {
    Invoke-Stop
    Start-Sleep -Milliseconds 500
    Invoke-Start
}

function Invoke-Status {
    $owner = Get-PortOwner
    $alive = if ($owner) { Test-Responding } else { $false }

    Write-Host ""
    Write-Host "webui status" -ForegroundColor Cyan
    Write-Host ("  port {0,-6} " -f $Port) -NoNewline

    if ($owner) {
        Write-Host ("LISTENING (PID {0})" -f $owner.Pid) -ForegroundColor Green
        if ($owner.IsWebui) {
            Write-Host ("  process     {0} (started {1:yyyy-MM-dd HH:mm:ss})" -f $owner.Name, $owner.StartTime)
        } else {
            Write-Host ("  process     OTHER: {0} -- not the webui" -f $owner.Name) -ForegroundColor Yellow
        }
        if ($owner.CommandLine) {
            Write-Host ("  command     {0}" -f $owner.CommandLine)
        }
        Write-Host "  api         " -NoNewline
        if ($alive) { Write-Host "OK ($ReadyUrl)" -ForegroundColor Green }
        else        { Write-Host "unreachable ($ReadyUrl)" -ForegroundColor Yellow }
    } else {
        Write-Host "free" -ForegroundColor DarkGray
        Write-Host "  process     none"
    }

    if ($owner) {
        $treeMembers = @(Get-WebuiTreeMembers -AnchorPid $owner.Pid)
        if ($treeMembers.Count -gt 0) {
            $list = ($treeMembers | ForEach-Object { "PID $($_.ProcessId)" }) -join ', '
            Write-Host ("  tree        {0}" -f $list) -ForegroundColor Gray
            Write-Host  "              (parent/child of listener -- normal for uvicorn on Windows)"
        }
    }

    $anchorPid = if ($owner) { $owner.Pid } else { 0 }
    $orphans = @(Get-Orphans -AnchorPid $anchorPid)
    if ($orphans.Count -gt 0) {
        $list = ($orphans | ForEach-Object { "PID $($_.ProcessId)" }) -join ', '
        Write-Host ("  orphans     {0}" -f $list) -ForegroundColor Yellow
        Write-Host  "              (run '.\webui.ps1 kill' to clean up)"
    }

    if (Test-Path $LogFile) {
        $sz = (Get-Item $LogFile).Length
        Write-Host ("  log         {0} ({1})" -f $LogFile, (Format-Bytes $sz))
    }
    if (Test-Path $ErrFile) {
        $sz = (Get-Item $ErrFile).Length
        $color = if ($sz -gt 0) { 'Yellow' } else { 'Gray' }
        Write-Host ("  log.err     {0} ({1})" -f $ErrFile, (Format-Bytes $sz)) -ForegroundColor $color
    }
    if (Test-Path $PidFile) {
        Write-Host ("  pid file    {0}" -f $PidFile) -ForegroundColor Gray
    }
    Write-Host ""
}

function Invoke-Logs {
    $files = if ($Both) { @($LogFile, $ErrFile) }
             elseif ($Err) { @($ErrFile) }
             else  { @($LogFile) }

    foreach ($f in $files) {
        if (-not (Test-Path $f)) { Write-Warning "log not found: $f" }
    }
    $files = @($files | Where-Object { Test-Path $_ })
    if ($files.Count -eq 0) { return }

    if ($Static) {
        foreach ($f in $files) {
            Write-Host "── $f (last $Tail) ──" -ForegroundColor Cyan
            Get-Content $f -Tail $Tail
        }
        return
    }

    if ($Both) {
        $jobs = @(
            Start-Job -ArgumentList $LogFile, $Tail -ScriptBlock {
                param($f, $n)
                Get-Content -Path $f -Wait -Tail $n | ForEach-Object { "[OUT] $_" }
            }
            Start-Job -ArgumentList $ErrFile, $Tail -ScriptBlock {
                param($f, $n)
                Get-Content -Path $f -Wait -Tail $n | ForEach-Object { "[ERR] $_" }
            }
        )
        Write-Host "tailing $LogFile + $ErrFile (Ctrl+C to exit)" -ForegroundColor Cyan
        try {
            while ($true) {
                $jobs | Receive-Job | ForEach-Object {
                    if ($_.StartsWith('[ERR]')) { Write-Host $_ -ForegroundColor Yellow }
                    else                       { Write-Host $_ }
                }
                Start-Sleep -Milliseconds 200
            }
        } finally {
            $jobs | Stop-Job -ErrorAction SilentlyContinue
            $jobs | Remove-Job -Force -ErrorAction SilentlyContinue
        }
    } else {
        $f = $files[0]
        Write-Host "tailing $f (Ctrl+C to exit)" -ForegroundColor Cyan
        Get-Content -Path $f -Wait -Tail $Tail
    }
}

function Invoke-Monitor {
    # Atomic-redraw monitor: builds each frame as a single string with
    # embedded ANSI codes (color + clear-to-EOL + cursor-home + clear-to-EOS)
    # and writes it in one Console.Write call. No intermediate blank state,
    # so no flicker. Requires VT-enabled terminal (Win11 default) and an
    # interactive console host (cannot run inside Start-Job / redirected pipe).
    if ([Console]::IsOutputRedirected) {
        Write-Error "monitor requires an interactive console (output is redirected). Use 'status' for one-shot snapshots."
        return
    }
    $ESC = [char]27
    $K       = "$ESC[K"           # clear from cursor to end of line
    $J       = "$ESC[J"           # clear from cursor to end of screen
    $RST     = "$ESC[0m"          # reset attributes
    $ALT_ON  = "$ESC[?1049h"      # enter alternate screen buffer
    $ALT_OFF = "$ESC[?1049l"      # leave alternate screen buffer
    $HIDE    = "$ESC[?25l"
    $SHOW    = "$ESC[?25h"
    $FG_CYAN  = "$ESC[36m"
    $FG_GREEN = "$ESC[32m"
    $FG_YEL   = "$ESC[33m"
    $FG_GRAY  = "$ESC[90m"
    $FG_DCY   = "$ESC[36m"
    $FG_DYEL  = "$ESC[33m"

    # Enter alternate screen buffer + hide cursor + reset attrs in one write
    # so the very first paint is clean and the original scrollback is preserved
    [Console]::Write("${ALT_ON}${HIDE}${RST}")

    try {
        while ($true) {
            $owner = Get-PortOwner
            $alive = if ($owner) { Test-Responding } else { $false }

            # Kernel-level cursor home before any VT bytes hit the wire.
            # SetCursorPosition is a single Win32 call; \e[H would race the
            # rendering pipeline.
            try { [Console]::SetCursorPosition(0, 0) } catch { }

            $sb = [System.Text.StringBuilder]::new(4096)
            # Reset attributes first so previous frame's color state can't
            # leak into the cleared regions of this frame
            [void]$sb.Append($RST)

            [void]$sb.AppendLine("${K}")
            [void]$sb.AppendLine("${FG_CYAN}webui status${RST}${K}")

            if ($owner) {
                [void]$sb.AppendLine(("  port {0,-6} ${FG_GREEN}LISTENING (PID {1}){2}${K}" -f $Port, $owner.Pid, $RST))
                if ($owner.IsWebui) {
                    [void]$sb.AppendLine(("  process     {0} (started {1:yyyy-MM-dd HH:mm:ss}){2}" -f $owner.Name, $owner.StartTime, $K))
                } else {
                    [void]$sb.AppendLine(("  process     ${FG_YEL}OTHER: {0} -- not the webui${RST}{1}" -f $owner.Name, $K))
                }
                if ($alive) {
                    [void]$sb.AppendLine("  api         ${FG_GREEN}OK${RST} ($ReadyUrl)${K}")
                } else {
                    [void]$sb.AppendLine("  api         ${FG_YEL}unreachable${RST} ($ReadyUrl)${K}")
                }
                $treeMembers = @(Get-WebuiTreeMembers -AnchorPid $owner.Pid)
                if ($treeMembers.Count -gt 0) {
                    $list = ($treeMembers | ForEach-Object { "PID $($_.ProcessId)" }) -join ', '
                    [void]$sb.AppendLine("  tree        ${FG_GRAY}${list}${RST}${K}")
                }
            } else {
                [void]$sb.AppendLine(("  port {0,-6} ${FG_GRAY}free${RST}{1}" -f $Port, $K))
                [void]$sb.AppendLine("  process     none${K}")
            }

            $anchor = if ($owner) { $owner.Pid } else { 0 }
            $orphans = @(Get-Orphans -AnchorPid $anchor)
            if ($orphans.Count -gt 0) {
                $list = ($orphans | ForEach-Object { "PID $($_.ProcessId)" }) -join ', '
                [void]$sb.AppendLine("  orphans     ${FG_YEL}${list}${RST}${K}")
            }

            if (Test-Path $LogFile) {
                $sz = (Get-Item $LogFile).Length
                [void]$sb.AppendLine(("  log         {0} ({1}){2}" -f $LogFile, (Format-Bytes $sz), $K))
            }
            if (Test-Path $ErrFile) {
                $sz = (Get-Item $ErrFile).Length
                $col = if ($sz -gt 0) { $FG_YEL } else { $FG_GRAY }
                [void]$sb.AppendLine(("  log.err     {0}{1} ({2}){3}{4}" -f $col, $ErrFile, (Format-Bytes $sz), $RST, $K))
            }
            [void]$sb.AppendLine($K)

            if (Test-Path $LogFile) {
                [void]$sb.AppendLine("${FG_DCY}-- recent stdout (last 5) --${RST}${K}")
                $lines = @(Get-Content $LogFile -Tail 5 -ErrorAction SilentlyContinue)
                foreach ($l in $lines) { [void]$sb.AppendLine("${l}${K}") }
                # Pad to fixed 5 lines so a shrinking log doesn't leave residue
                for ($i = $lines.Count; $i -lt 5; $i++) { [void]$sb.AppendLine($K) }
                [void]$sb.AppendLine($K)
            }

            if ((Test-Path $ErrFile) -and ((Get-Item $ErrFile).Length -gt 0)) {
                [void]$sb.AppendLine("${FG_DYEL}-- recent stderr (last 3) --${RST}${K}")
                $lines = @(Get-Content $ErrFile -Tail 3 -ErrorAction SilentlyContinue)
                foreach ($l in $lines) { [void]$sb.AppendLine("${l}${K}") }
                for ($i = $lines.Count; $i -lt 3; $i++) { [void]$sb.AppendLine($K) }
                [void]$sb.AppendLine($K)
            }

            [void]$sb.AppendLine("${FG_GRAY}(refreshing every 2s, Ctrl+C to exit)${RST}${K}")
            [void]$sb.Append($J)  # wipe any tail lines from a previous longer frame

            [Console]::Write($sb.ToString())
            Start-Sleep -Seconds 2
        }
    } finally {
        # Leave alternate buffer (restores original scrollback) + show cursor
        [Console]::Write("${RST}${SHOW}${ALT_OFF}")
        Write-Host "monitor exited"
    }
}

function Show-Help {
@"
webui.ps1 - MusIQ-Lab webui Windows lifecycle helper

USAGE
  .\webui.ps1 <command> [options]

COMMANDS
  start          Detached launch on port $Port. Idempotent if already responsive.
                 Polls /api/tracks for readiness up to ${ReadyTimeoutSec}s.
                 (Each start truncates webui.log and webui.log.err.)
  stop           Graceful stop of port owner; force fallback after 3s.
  kill           Force-kill port owner + sweep any python -m webui orphans.
  restart        stop, then start.
  status         Port owner, our-process check, API health, orphans, log sizes.
  logs           Live-tail webui.log (Ctrl+C exits).
       -Err      Tail webui.log.err instead.
       -Both     Interleave both with [OUT]/[ERR] prefixes.
       -Tail N   Initial buffer (default 20).
       -Static   Print last N lines and exit; do not follow.
  monitor        Refresh status + last log lines every 2s.
  help           Show this message.

EXAMPLES
  .\webui.ps1 start
  .\webui.ps1 status
  .\webui.ps1 monitor
  .\webui.ps1 logs -Err
  .\webui.ps1 logs -Both -Tail 50
  .\webui.ps1 logs -Static -Tail 200
  .\webui.ps1 restart

NOTES
  - Foreground dev (with --reload) still uses run.bat; this script is for
    detached / managed runs only.
  - The bash scripts under ../scripts/webui-*.sh are non-functional on
    Windows (Linux-only primitives) -- use this script instead.
"@
}

# ---- Dispatch ------------------------------------------------------------

switch ($Command) {
    'start'    { Invoke-Start }
    'stop'     { Invoke-Stop }
    'kill'     { Invoke-Stop -Force }
    'restart'  { Invoke-Restart }
    'status'   { Invoke-Status }
    'logs'     { Invoke-Logs }
    'monitor'  { Invoke-Monitor }
    'help'     { Show-Help }
    default    { Show-Help }
}
