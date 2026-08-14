@echo off
taskkill /f /im 麦克风声强显示器.exe >nul 2>&1
start "" "%~dp0dist\麦克风声强显示器.exe"
