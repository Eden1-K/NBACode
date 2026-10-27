@echo off
REM Creates a Windows scheduled task that updates the ladder every day at 6:30 pm.
REM Run once (double-click). To remove it later: schtasks /delete /tn "NBA Ladder Update" /f
schtasks /create /tn "NBA Ladder Update" /tr "\"%~dp0run_ladder.bat\" quiet" /sc daily /st 18:30 /f
echo.
echo Done - the ladder will update every day at 6:30 pm while this PC is on.
pause
