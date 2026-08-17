@echo off
setlocal enabledelayedexpansion

:: SSL Certificate Manager - Docker Management Script (Windows)
:: Usage: certmanager.bat [start|stop|restart|destroy|status|logs|build]

set SCRIPT_DIR=%~dp0
set COMPOSE_FILE=%SCRIPT_DIR%docker-compose.yml
set CONTAINER_NAME=ssl-cert-manager

if "%~1"=="" goto :usage

if /i "%~1"=="start" goto :start
if /i "%~1"=="stop" goto :stop
if /i "%~1"=="restart" goto :restart
if /i "%~1"=="destroy" goto :destroy
if /i "%~1"=="status" goto :status
if /i "%~1"=="logs" goto :logs
if /i "%~1"=="build" goto :build
if /i "%~1"=="key" goto :key
if /i "%~1"=="regenerate" goto :regenerate
goto :usage

:start
echo === Starting SSL Certificate Manager ===
echo.
docker compose -f "%COMPOSE_FILE%" up -d --build
echo.
echo Started. Access at: http://localhost
echo API docs at: http://localhost/api/docs
echo.
echo First run? Check the API key with: certmanager.bat key
goto :eof

:stop
echo === Stopping SSL Certificate Manager ===
docker compose -f "%COMPOSE_FILE%" stop
echo Stopped. Data is preserved.
goto :eof

:restart
echo === Restarting SSL Certificate Manager ===
docker compose -f "%COMPOSE_FILE%" restart
echo Restarted.
goto :eof

:destroy
echo === Destroying SSL Certificate Manager ===
echo.
echo WARNING: This will remove the container.
set /p CONFIRM=Remove data volume too? (y/N): 
if /i "!CONFIRM!"=="y" (
    echo Removing container AND data volume...
    docker compose -f "%COMPOSE_FILE%" down -v
    echo Container and data volume REMOVED. All certificates and keys are gone.
) else (
    echo Removing container only (data preserved in volume)...
    docker compose -f "%COMPOSE_FILE%" down
    echo Container removed. Data volume preserved - next start will reuse existing keys and database.
)
goto :eof

:status
echo === SSL Certificate Manager Status ===
echo.
docker compose -f "%COMPOSE_FILE%" ps
echo.
echo --- Health Check ---
curl -s http://localhost/api/v1/health 2>nul
if errorlevel 1 (
    echo Service not reachable. Is it running?
) else (
    echo.
)
goto :eof

:logs
echo === SSL Certificate Manager Logs ===
echo (Press Ctrl+C to exit)
echo.
docker compose -f "%COMPOSE_FILE%" logs -f --tail=50
goto :eof

:build
echo === Rebuilding SSL Certificate Manager ===
docker compose -f "%COMPOSE_FILE%" build --no-cache
echo Build complete. Run 'certmanager.bat start' to start.
goto :eof

:key
echo === API Key ===
echo.
docker exec %CONTAINER_NAME% cat /data/.api_key 2>nul
if errorlevel 1 (
    echo Could not read API key. Is the container running?
    echo Try: certmanager.bat start
) else (
    echo.
    echo Paste this into Settings in the browser.
)
goto :eof

:regenerate
:: Deliberately its own explicit command, not wired into :start or :build -
:: the About page's Regenerate action overwrites its current content
:: wholesale, including any hand-added notes (e.g. a license-review
:: sign-off), so it should only run when someone actually means it, not as
:: a side effect of every routine restart.
echo === Regenerating About Page ===
echo.
echo NOTE: This overwrites the current About page content, including any hand-added notes.
echo.
set API_KEY=
for /f "delims=" %%k in ('docker exec %CONTAINER_NAME% cat /data/.api_key 2^>nul') do set API_KEY=%%k
if "%API_KEY%"=="" (
    echo Could not read API key. Is the container running?
    goto :eof
)
curl -s -X POST -H "X-API-Key: %API_KEY%" http://localhost/api/v1/about/regenerate
if errorlevel 1 (
    echo.
    echo Failed to regenerate. Is the container running and healthy?
) else (
    echo.
    echo Done.
)
goto :eof

:usage
echo.
echo SSL Certificate Manager - Docker Management
echo.
echo Usage: certmanager.bat [command]
echo.
echo Commands:
echo   start     Build and start the application
echo   stop      Stop the application (data preserved)
echo   restart   Restart the application
echo   destroy   Remove container (prompts to remove data)
echo   status    Show container status and health
echo   logs      Follow live container logs
echo   build     Rebuild the image without starting
echo   key         Show the API key
echo   regenerate  Rebuild the About page's dependency versions (overwrites hand-added notes - run deliberately, e.g. after a rebuild that bumped a dependency)
echo.
echo Examples:
echo   certmanager.bat start        Start for the first time
echo   certmanager.bat key          Get the API key to paste into browser
echo   certmanager.bat regenerate   Refresh About page versions after a rebuild
echo   certmanager.bat destroy      Remove everything
echo.
goto :eof
