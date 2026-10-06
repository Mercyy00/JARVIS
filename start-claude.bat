@echo off
title Claude Code (JARVIS)

REM Check if Python bridge is already running on port 8089
netstat -ano | findstr 8089 >nul 2>&1
if %errorlevel% neq 0 (
    echo Starting Claude Bridge proxy...
    start /b python "d:\engineers\JAY\claude_bridge.py"
    timeout /t 2 /nobreak >nul
)

set ANTHROPIC_BASE_URL=http://127.0.0.1:8089
set ANTHROPIC_API_KEY=sk-rj6jhoivAL5uGmKoBzQIWOK57YIZZEjAVGttGNa8XjdOI9u0

echo Claude Code initialized with custom API key.
claude --model claude-opus-4-8
