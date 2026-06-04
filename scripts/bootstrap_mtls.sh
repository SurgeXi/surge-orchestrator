#!/usr/bin/env bash
# Bootstrap SOL mTLS CA + server cert + client certs.
#
# Idempotent: existing files are NOT overwritten. If you need to regenerate,
# remove the relevant files under /etc/sol/{ca,server,clients} first.
#
# Layout produced:
#   /etc/sol/ca/sol-ca.{key,crt,srl}              (root 600 / root 644 / root 644)
#   /etc/sol/server/sol-server.{key,crt,csr}      (root 600 / root 644 / root 644)
#   /etc/sol/clients/<name>.client.{key,crt,csr}  (root 600 / root 644 / root 644)
#
# Run as root on surgecore. Idempotent: re-runs only fill in missing pieces.
#
# Args:
#   $1 = action (init | add-client <name>)
#
set -euo pipefail

CA_DIR=/etc/sol/ca
SRV_DIR=/etc/sol/server
CLI_DIR=/etc/sol/clients
SAN_DNS_LIST="DNS:sol.surgecore.internal,DNS:surgecore-dell.tail-scale.ts.net,DNS:localhost,IP:127.0.0.1,IP:100.98.123.125"
CA_CN="SurgeXi SOL Internal CA"
SRV_CN="sol.surgecore.internal"

mkdir -p "$CA_DIR" "$SRV_DIR" "$CLI_DIR"
chmod 750 "$CA_DIR" "$SRV_DIR" "$CLI_DIR"

ensure_ca() {
    if [[ -f "$CA_DIR/sol-ca.key" && -f "$CA_DIR/sol-ca.crt" ]]; then
        echo "  CA already present (skipping init)."
        return
    fi
    echo "  generating SOL CA private key (RSA 4096) ..."
    openssl genrsa -out "$CA_DIR/sol-ca.key" 4096 >/dev/null 2>&1
    chmod 600 "$CA_DIR/sol-ca.key"

    echo "  self-signing CA cert (10 years) ..."
    openssl req -x509 -new -nodes \
        -key "$CA_DIR/sol-ca.key" \
        -sha256 \
        -days 3650 \
        -subj "/C=US/O=SurgeXi/OU=SOL/CN=${CA_CN}" \
        -out "$CA_DIR/sol-ca.crt" >/dev/null 2>&1
    chmod 644 "$CA_DIR/sol-ca.crt"

    # Serial tracking file used by `openssl x509 -CAcreateserial`.
    echo 1000 > "$CA_DIR/sol-ca.srl"
    chmod 644 "$CA_DIR/sol-ca.srl"
    echo "  CA installed in $CA_DIR"
}

ensure_server_cert() {
    if [[ -f "$SRV_DIR/sol-server.key" && -f "$SRV_DIR/sol-server.crt" ]]; then
        echo "  server cert already present (skipping)."
        return
    fi
    echo "  generating server key + CSR ..."
    openssl genrsa -out "$SRV_DIR/sol-server.key" 2048 >/dev/null 2>&1
    chmod 600 "$SRV_DIR/sol-server.key"

    openssl req -new \
        -key "$SRV_DIR/sol-server.key" \
        -subj "/C=US/O=SurgeXi/OU=SOL/CN=${SRV_CN}" \
        -out "$SRV_DIR/sol-server.csr" >/dev/null 2>&1

    # Extensions file for SAN — discarded after signing
    local extfile
    extfile=$(mktemp)
    cat > "$extfile" <<EOF
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = ${SAN_DNS_LIST}
EOF

    echo "  signing server cert (1 year, SAN=${SAN_DNS_LIST}) ..."
    openssl x509 -req -in "$SRV_DIR/sol-server.csr" \
        -CA "$CA_DIR/sol-ca.crt" \
        -CAkey "$CA_DIR/sol-ca.key" \
        -CAserial "$CA_DIR/sol-ca.srl" \
        -extfile "$extfile" \
        -sha256 \
        -days 365 \
        -out "$SRV_DIR/sol-server.crt" >/dev/null 2>&1
    rm -f "$extfile"

    chmod 644 "$SRV_DIR/sol-server.crt"
    echo "  server cert installed in $SRV_DIR"
}

issue_client_cert() {
    local name=$1
    local cn="${name}.sol-client"
    local key="$CLI_DIR/${name}.client.key"
    local csr="$CLI_DIR/${name}.client.csr"
    local crt="$CLI_DIR/${name}.client.crt"

    if [[ -f "$key" && -f "$crt" ]]; then
        echo "  client cert ${name} already present (skipping)."
        return
    fi

    echo "  generating client key + CSR for ${name} (CN=${cn}) ..."
    openssl genrsa -out "$key" 2048 >/dev/null 2>&1
    chmod 600 "$key"

    openssl req -new \
        -key "$key" \
        -subj "/C=US/O=SurgeXi/OU=SOL/CN=${cn}" \
        -out "$csr" >/dev/null 2>&1

    local extfile
    extfile=$(mktemp)
    cat > "$extfile" <<EOF
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = clientAuth
EOF

    echo "  signing client cert ${name} (1 year) ..."
    openssl x509 -req -in "$csr" \
        -CA "$CA_DIR/sol-ca.crt" \
        -CAkey "$CA_DIR/sol-ca.key" \
        -CAserial "$CA_DIR/sol-ca.srl" \
        -extfile "$extfile" \
        -sha256 \
        -days 365 \
        -out "$crt" >/dev/null 2>&1
    rm -f "$extfile"

    chmod 644 "$crt"
    echo "  client cert installed: ${crt}"
}

action=${1:-init}
case "$action" in
    init)
        ensure_ca
        ensure_server_cert
        for name in brain broker surge-runner sol-admin; do
            issue_client_cert "$name"
        done
        echo
        echo "SOL mTLS bootstrap complete."
        echo "  CA cert:     $CA_DIR/sol-ca.crt"
        echo "  Server cert: $SRV_DIR/sol-server.crt"
        echo "  Client certs (in $CLI_DIR):"
        ls -la "$CLI_DIR"/*.crt 2>/dev/null || true
        ;;
    add-client)
        if [[ $# -lt 2 ]]; then
            echo "Usage: $0 add-client <name>" >&2
            exit 2
        fi
        issue_client_cert "$2"
        ;;
    *)
        echo "Unknown action: $action" >&2
        echo "Usage: $0 [init | add-client <name>]" >&2
        exit 2
        ;;
esac
