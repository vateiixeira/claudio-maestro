"""agentd: keeps the `claude` processes alive across backend restarts. Stdlib only."""

PROTOCOL = 1
SOCKET_NAME = f"agentd-v{PROTOCOL}.sock"
LOCK_NAME = f"agentd-v{PROTOCOL}.lock"
LOG_NAME = "agentd.log"
