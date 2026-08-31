#!/usr/bin/env bash
set -u
set -o pipefail

export PATH="/opt/piavpn/bin:${PATH}"
export LD_LIBRARY_PATH="/opt/piavpn/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"

WORKER_ID="${WORKER_ID:-worker}"
TOKEN_SLOT="${TOKEN_SLOT:-1}"
CREDENTIALS_CONTAINER_PATH="${CREDENTIALS_CONTAINER_PATH:-/app/credentials}"
PIA_ACCOUNT_PATH="${PIA_ACCOUNT_PATH:-${PIA_TOKEN_PATH:-${CREDENTIALS_CONTAINER_PATH}/pia_account_${TOKEN_SLOT}}}"
PIA_PROTOCOL="${PIA_PROTOCOL:-auto}"

SOCKS5_PORT="${SOCKS5_PORT:-1080}"
SOCKS5_USERNAME="${SOCKS5_USERNAME:-}"
SOCKS5_PASSWORD="${SOCKS5_PASSWORD:-}"
PROXY_CONTROL_PORT="${PROXY_CONTROL_PORT:-9000}"
PROXY_LOG_PATH="${PROXY_LOG_PATH:-/tmp/proxy-runtime.log}"
CLI_STATUS_LOOP_INTERVAL_SECONDS="${CLI_STATUS_LOOP_INTERVAL_SECONDS:-30}"
PIA_CLI_LOCK_PATH="${PIA_CLI_LOCK_PATH:-/tmp/piactl.lock}"

SESSION_FILE="${CREDENTIALS_CONTAINER_PATH}/pia_session_slot_${TOKEN_SLOT}.json"

SOCKS_PID=""
CONTROL_PID=""
DAEMON_PID=""

mkdir -p "$(dirname "$PROXY_LOG_PATH")"
touch "$PROXY_LOG_PATH"
exec > >(tee -a "$PROXY_LOG_PATH") 2>&1

log() {
    printf '[entrypoint] %s\n' "$*"
}

cleanup() {
    log "Shutting down worker..."
    timeout -k 1 3s flock -w 2 "${PIA_CLI_LOCK_PATH}" piactl disconnect >/dev/null 2>&1 || true
    if [[ -n "${SOCKS_PID}" ]]; then kill -9 "${SOCKS_PID}" 2>/dev/null || true; fi
    if [[ -n "${CONTROL_PID}" ]]; then kill -9 "${CONTROL_PID}" 2>/dev/null || true; fi
    if [[ -n "${DAEMON_PID}" ]]; then kill -9 "${DAEMON_PID}" 2>/dev/null || true; fi
}
trap cleanup EXIT INT TERM

enable_killswitch() {
    log "Applying strict VPN killswitch iptables rules..."
    iptables -F OUTPUT 2>/dev/null || true
    iptables -A OUTPUT -o lo -j ACCEPT 2>/dev/null || true
    iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || true
    iptables -A OUTPUT -d 10.0.0.0/8 -j ACCEPT 2>/dev/null || true
    iptables -A OUTPUT -d 172.16.0.0/12 -j ACCEPT 2>/dev/null || true
    iptables -A OUTPUT -d 192.168.0.0/16 -j ACCEPT 2>/dev/null || true
    iptables -A OUTPUT -o wgpia+ -j ACCEPT 2>/dev/null || true
    iptables -A OUTPUT -o tun+ -j ACCEPT 2>/dev/null || true
    iptables -A OUTPUT -p udp --dport 53 -j ACCEPT 2>/dev/null || true
    iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT 2>/dev/null || true
    iptables -A OUTPUT -p udp -m multiport --dports 1194,1197,1198,8080,1337,51820 -j ACCEPT 2>/dev/null || true
    iptables -A OUTPUT -p tcp -m multiport --dports 443,8443,1337 -j ACCEPT 2>/dev/null || true
    iptables -A OUTPUT -o eth0 -j DROP 2>/dev/null || true
}

start_dbus() {
    if [[ ! -s /etc/machine-id ]] || ! grep -qE '^[0-9a-fA-F]{32}$' /etc/machine-id 2>/dev/null; then
        log "Generating missing D-Bus machine ID"
        dbus-uuidgen > /etc/machine-id 2>/dev/null || true
        chmod 444 /etc/machine-id 2>/dev/null || true
    fi

    if [[ -S /run/dbus/system_bus_socket ]] && dbus-send --system \
        --dest=org.freedesktop.DBus --type=method_call --print-reply \
        /org/freedesktop/DBus org.freedesktop.DBus.ListNames >/dev/null 2>&1; then
        return 0
    fi

    log "Starting D-Bus system bus"
    mkdir -p /run/dbus
    rm -f /run/dbus/system_bus_socket
    dbus-daemon --system --fork --nopidfile
}

wait_for_cli() {
    log "Waiting for piactl"
    for _ in $(seq 1 30); do
        if command -v piactl >/dev/null 2>&1 && piactl --help >/tmp/pia-help.txt 2>&1; then
            return 0
        fi
        sleep 0.5
    done
    log "piactl did not become ready. Last output:"
    cat /tmp/pia-help.txt 2>/dev/null || true
    return 1
}

preload_session_if_available() {
    mkdir -p /opt/piavpn/etc
    if [[ -f "$SESSION_FILE" && -s "$SESSION_FILE" ]] && grep -q '"loggedIn":true' "$SESSION_FILE" 2>/dev/null; then
        cp "$SESSION_FILE" /opt/piavpn/etc/account.json
        chown -R root:piavpn /opt/piavpn/etc 2>/dev/null || true
        chmod 600 /opt/piavpn/etc/account.json 2>/dev/null || true
        log "Preloaded PIA account session from ${SESSION_FILE}"
    fi
}

wait_for_daemon_sock() {
    for _ in $(seq 1 40); do
        if [[ -S /opt/piavpn/var/daemon.sock ]]; then
            return 0
        fi
        sleep 0.25
    done
    return 1
}

start_pia_daemon() {
    if [[ -S /opt/piavpn/var/daemon.sock ]] && pgrep -f "pia-daemon" >/dev/null 2>&1; then
        log "PIA daemon already running"
        return 0
    fi
    if [[ ! -x /opt/piavpn/bin/pia-daemon ]]; then
        log "PIA daemon binary is missing" >&2
        return 1
    fi
    log "Starting PIA daemon"
    /opt/piavpn/bin/pia-daemon >/tmp/pia-daemon.log 2>&1 &
    DAEMON_PID=$!
    if wait_for_daemon_sock; then
        log "PIA daemon socket is ready"
    else
        log "PIA daemon socket wait completed"
    fi
    return 0
}

enable_background_mode() {
    for _ in $(seq 1 10); do
        if timeout -k 2 10s flock -w 5 "${PIA_CLI_LOCK_PATH}" piactl background enable >/tmp/pia-background.txt 2>&1; then
            log "PIA background mode is enabled"
            return 0
        fi
        sleep 0.5
    done
    log "PIA background mode could not be enabled yet"
    cat /tmp/pia-background.txt >&2 || true
    return 0
}

wait_for_listen() {
    local port="$1"
    local name="$2"
    for _ in $(seq 1 20); do
        if ss -ltnH | awk '{print $4}' | grep -Eq "(:|\])${port}$"; then
            log "${name} is listening on port ${port}"
            return 0
        fi
        sleep 0.25
    done
    log "${name} did not start listening on port ${port}" >&2
    ss -ltnp >&2 || true
    return 1
}

start_control_api() {
    log "Starting proxy control API on 0.0.0.0:${PROXY_CONTROL_PORT}"
    python3 /usr/local/bin/proxy-control-server.py &
    CONTROL_PID=$!
}

start_socks5() {
    local args=(-i 0.0.0.0 -p "$SOCKS5_PORT")
    if [[ -n "$SOCKS5_USERNAME" || -n "$SOCKS5_PASSWORD" ]]; then
        args+=(-u "$SOCKS5_USERNAME" -P "$SOCKS5_PASSWORD")
    fi
    log "Starting SOCKS5 on 0.0.0.0:${SOCKS5_PORT}"
    microsocks "${args[@]}" &
    SOCKS_PID=$!
    wait_for_listen "$SOCKS5_PORT" "SOCKS5" || true
}

# Small startup stagger to prevent thundering herd on kernel netlink locks
worker_num=$(echo "$WORKER_ID" | tr -dc '0-9')
if [[ -n "$worker_num" ]]; then
    stagger_ms=$(( (worker_num % 10) * 150 ))
    if [[ $stagger_ms -gt 0 ]]; then
        sleep "0.${stagger_ms}" 2>/dev/null || true
    fi
fi

preload_session_if_available
start_dbus
wait_for_cli
start_control_api
start_socks5
auto_login_and_connect() {
    local target="${PIA_STARTUP_TARGET:-random}"
    local is_logged_in=false
    if [[ -f "/opt/piavpn/etc/account.json" ]] && grep -q '"loggedIn":true' "/opt/piavpn/etc/account.json" 2>/dev/null; then
        is_logged_in=true
        log "Account session is preloaded and active."
    fi

    if [[ "$is_logged_in" != "true" && -f "$PIA_ACCOUNT_PATH" && -s "$PIA_ACCOUNT_PATH" ]]; then
        log "Attempting startup login using ${PIA_ACCOUNT_PATH}..."
        if timeout -k 2 45s flock -w 20 "${PIA_CLI_LOCK_PATH}" piactl login "$PIA_ACCOUNT_PATH" >/dev/null 2>&1; then
            is_logged_in=true
            if [[ -f "/opt/piavpn/etc/account.json" && -w "/app/credentials" ]]; then
                cp /opt/piavpn/etc/account.json /app/credentials/pia_session_slot_1.json 2>/dev/null || true
                chmod 600 /app/credentials/pia_session_slot_1.json 2>/dev/null || true
            fi
        fi
    fi

    if [[ "${PIA_CONNECT_ON_STARTUP:-true}" == "true" ]]; then
        if [[ -n "$target" && "$target" != "random" && "$target" != "__random__" && "$target" != "any" && "$target" != "all" && "$target" != "auto" ]]; then
            timeout -k 2 20s flock -w 10 "${PIA_CLI_LOCK_PATH}" piactl set region "$target" >/dev/null 2>&1 || true
        else
            local fallback_regions=(
                "us-california" "us-new-york" "us-chicago" "us-texas" "us-florida" "us-seattle" "us-atlanta" "us-denver" "us-virginia" "us-ohio"
                "ca-ontario" "ca-toronto" "ca-vancouver" "ca-montreal" "uk-london" "uk-manchester" "germany" "france" "netherlands" "sweden"
                "switzerland" "norway" "denmark" "finland" "austria" "belgium" "ireland" "italy" "spain" "poland"
                "singapore" "japan" "taiwan" "south-korea" "australia" "au-sydney" "au-melbourne" "au-perth" "new-zealand" "brazil"
                "mexico" "albania" "armenia" "cyprus" "czech-republic" "estonia" "georgia" "greece" "hungary" "iceland"
                "india" "israel" "kazakhstan" "latvia" "lithuania" "luxembourg" "moldova" "monaco" "montenegro" "north-macedonia"
                "portugal" "romania" "serbia" "slovakia" "slovenia" "south-africa" "turkey" "ukraine" "united-arab-emirates"
            )
            local target_region=""
            if [[ -n "$worker_num" && "$worker_num" -gt 0 ]]; then
                local idx=$(( (worker_num - 1) % ${#fallback_regions[@]} ))
                target_region="${fallback_regions[$idx]}"
            fi
            if [[ -z "$target_region" ]]; then
                target_region=$(timeout -k 2 15s flock -w 10 "${PIA_CLI_LOCK_PATH}" piactl get regions 2>/dev/null | grep -v "^auto$" | shuf -n 1 || echo "singapore")
            fi
            timeout -k 2 20s flock -w 10 "${PIA_CLI_LOCK_PATH}" piactl set region "$target_region" >/dev/null 2>&1 || true
        fi
        timeout -k 2 35s flock -w 15 "${PIA_CLI_LOCK_PATH}" piactl connect >/dev/null 2>&1 || true
    fi
}

start_pia_daemon
enable_background_mode
auto_login_and_connect
enable_killswitch

log "PIA CLI + SOCKS5 proxy container is ready. Backend will call the internal proxy control API."

while true; do
    if [[ -n "$SOCKS_PID" ]] && ! kill -0 "$SOCKS_PID" 2>/dev/null; then
        log "SOCKS5 process stopped" >&2
        exit 1
    fi
    if [[ -n "$CONTROL_PID" ]] && ! kill -0 "$CONTROL_PID" 2>/dev/null; then
        log "Proxy control API stopped" >&2
        exit 1
    fi
    sleep "${CLI_STATUS_LOOP_INTERVAL_SECONDS}" &
    wait $!
done
