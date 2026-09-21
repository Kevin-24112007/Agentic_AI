@echo off
echo Initializing Git and pushing to GitHub repository Kevin-24112007/agentic_ai...
cd /d "%~dp0"

git init
git add .
git commit -m "feat: initial commit for Campus Leave Agent"
git branch -M main
git remote add origin https://github.com/Kevin-24112007/agentic_ai.git
git push -u origin main

echo.
echo Upload process completed! Check your repo at: https://github.com/Kevin-24112007/agentic_ai
pause
