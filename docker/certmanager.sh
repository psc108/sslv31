#!/usr/bin/env bash
# SSL Certificate Manager - Docker Management Script (Linux/macOS)
# Usage: ./certmanager.sh [start|stop|restart|destroy|status|logs|build|key|regenerate|help]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
CONTAINER_NAME="ssl-cert-manager"

cmd_start() {
    echo "=== Starting SSL Certificate Manager ==="
    if ! docker network inspect docker_bm-net &>/dev/null; then
        echo "  Creating external network docker_bm-net..."
        docker network create docker_bm-net
    fi
    docker compose -f "$COMPOSE_FILE" up -d --build
    echo ""
    echo "  Started. Access at:  http://localhost"
    echo "  API docs at:         http://localhost/api/docs"
    echo ""
    echo "  First run? Get your API key with: ./certmanager.sh key"
}

cmd_stop() {
    echo "=== Stopping SSL Certificate Manager ==="
    docker compose -f "$COMPOSE_FILE" stop
    echo "Stopped. Data is preserved."
}

cmd_restart() {
    echo "=== Restarting SSL Certificate Manager ==="
    docker compose -f "$COMPOSE_FILE" restart
    echo "Restarted."
}

cmd_destroy() {
    echo "=== Destroying SSL Certificate Manager ==="
    echo ""
    read -rp "Remove data volume too? All certificates and keys will be PERMANENTLY DELETED (y/N): " confirm
    if [[ "$confirm" == "y" ]]; then
        echo "Removing container AND data volume..."
        docker compose -f "$COMPOSE_FILE" down -v
        echo "Container and data volume REMOVED."
    else
        echo "Removing container only (data preserved in volume)..."
        docker compose -f "$COMPOSE_FILE" down
        echo "Container removed. Volume preserved."
    fi
}

cmd_status() {
    echo "=== SSL Certificate Manager Status ==="
    echo ""
    docker compose -f "$COMPOSE_FILE" ps
    echo ""
    echo "--- Health Check ---"
    if health=$(curl -sf --max-time 5 http://localhost/api/v1/health); then
        echo "  Status:   $(echo "$health" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)"
        echo "  Version:  $(echo "$health" | grep -o '"version":"[^"]*"' | cut -d'"' -f4)"
        echo "  Database: $(echo "$health" | grep -o '"database":"[^"]*"' | cut -d'"' -f4)"
        echo "  Keytool:  $(echo "$health" | grep -o '"keytool":"[^"]*"' | cut -d'"' -f4)"
    else
        echo "  Service not reachable. Is it running?"
    fi
}

cmd_logs() {
    echo "=== SSL Certificate Manager Logs ==="
    echo "(Press Ctrl+C to exit)"
    docker compose -f "$COMPOSE_FILE" logs -f --tail=50
}

cmd_build() {
    echo "=== Rebuilding SSL Certificate Manager ==="
    docker compose -f "$COMPOSE_FILE" build --no-cache
    echo "Build complete. Run './certmanager.sh start' to start."
}

cmd_key() {
    echo "=== API Key ==="
    echo ""
    key=$(docker exec "$CONTAINER_NAME" cat /data/.api_key 2>/dev/null)
    if [[ -n "$key" ]]; then
        echo "  $key"
        echo ""
        echo "  Paste this into Settings in the browser."
    else
        echo "  Could not read API key. Is the container running?"
    fi
}

cmd_regenerate() {
    echo "=== Regenerating About Page ==="
    echo ""
    echo "  This overwrites the current About page content, including any hand-added notes."
    key=$(docker exec "$CONTAINER_NAME" cat /data/.api_key 2>/dev/null)
    if [[ -z "$key" ]]; then
        echo "  Could not read API key. Is the container running?"
        return 1
    fi
    if result=$(curl -sf --max-time 30 -X POST -H "X-API-Key: $key" http://localhost/api/v1/about/regenerate); then
        updated_by=$(echo "$result" | grep -o '"updated_by":"[^"]*"' | cut -d'"' -f4)
        updated_at=$(echo "$result" | grep -o '"updated_at":"[^"]*"' | cut -d'"' -f4)
        echo "  Done. Last updated by $updated_by at $updated_at."
    else
        echo "  Failed to regenerate. Is the container running and healthy?"
        return 1
    fi
}

show_help() {
    echo ""
    echo "SSL Certificate Manager - Docker Management"
    echo ""
    echo "Usage: ./certmanager.sh [command]"
    echo ""
    echo "Commands:"
    echo "  start       Build and start the application"
    echo "  stop        Stop the application (data preserved)"
    echo "  restart     Restart the application"
    echo "  destroy     Remove container (prompts to remove data)"
    echo "  status      Show container status and health"
    echo "  logs        Follow live container logs"
    echo "  build       Rebuild the image without starting"
    echo "  key         Show the API key"
    echo "  regenerate  Rebuild the About page's dependency versions (overwrites hand-added notes)"
    echo ""
    echo "Examples:"
    echo "  ./certmanager.sh start        # Start for the first time"
    echo "  ./certmanager.sh key          # Get the API key"
    echo "  ./certmanager.sh regenerate   # Refresh About page versions after a rebuild"
    echo "  ./certmanager.sh destroy      # Remove everything"
    echo ""
}

case "${1:-help}" in
    start)      cmd_start ;;
    stop)       cmd_stop ;;
    restart)    cmd_restart ;;
    destroy)    cmd_destroy ;;
    status)     cmd_status ;;
    logs)       cmd_logs ;;
    build)      cmd_build ;;
    key)        cmd_key ;;
    regenerate) cmd_regenerate ;;
    help)       show_help ;;
    *)          echo "Unknown command: $1"; show_help; exit 1 ;;
esac
