#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
server_dir="$repo_root/SERVER"
network="knu-mcp-gateway-test-$RANDOM-$RANDOM"
api_name="$network-api"
gateway_name="$network-gateway"
fixture_token="gateway-test-token"
created_env=false

cleanup() {
  docker rm -f "$gateway_name" "$api_name" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  if "$created_env"; then
    rm -f "$server_dir/.env"
  fi
}
trap cleanup EXIT

if [[ ! -e "$server_dir/.env" ]]; then
  umask 077
  printf 'DB_PASSWORD=gateway-test-db-password\nMCP_AUTH_TOKEN=%s\n' "$fixture_token" > "$server_dir/.env"
  created_env=true
fi

compose_config=$(cd "$server_dir" && MCP_AUTH_TOKEN="$fixture_token" DB_PASSWORD=gateway-test-db-password docker compose -f docker-compose.prod.yml config)
grep -Fq 'host_ip: 127.0.0.1' <<<"$compose_config"
grep -Fq 'published: "8000"' <<<"$compose_config"
grep -Fq "MCP_AUTH_TOKEN: $fixture_token" <<<"$compose_config"

docker network create "$network" >/dev/null
docker run -d --name "$api_name" --network "$network" --network-alias api \
  -v "$repo_root/WEB/tests/fixtures/mcp_gateway_api.Caddyfile:/etc/caddy/Caddyfile:ro" \
  caddy:2-alpine >/dev/null
docker run -d --name "$gateway_name" --network "$network" -e MCP_AUTH_TOKEN="$fixture_token" \
  -p 127.0.0.1::8000 -v "$repo_root/WEB/Caddyfile:/etc/caddy/Caddyfile:ro" \
  caddy:2-alpine >/dev/null

for _ in {1..20}; do
  endpoint=$(docker port "$gateway_name" 8000/tcp | head -n1 || true)
  if [[ -n "$endpoint" ]] && curl --silent --fail --max-time 1 "http://$endpoint/api/mcp" >/dev/null; then
    break
  fi
  sleep 0.25
done

[[ -n "${endpoint:-}" ]]
[[ $(curl --silent --fail --max-time 2 -H 'Authorization: Bearer client-token' "http://$endpoint/api/mcp") == "Bearer $fixture_token" ]]
[[ $(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 2 "http://$endpoint/api/health") == 404 ]]
