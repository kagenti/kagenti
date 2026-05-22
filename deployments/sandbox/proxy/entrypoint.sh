#!/bin/sh
# Kagenti sandbox proxy entrypoint
# Supports dynamic domain allowlist via ALLOWED_DOMAINS env var (comma-separated)
set -eu

CONFIG_FILE=/tmp/squid.conf
cp /etc/squid/squid.conf "$CONFIG_FILE"

# Override domains if ALLOWED_DOMAINS is set
if [ -n "${ALLOWED_DOMAINS:-}" ]; then
    # Remove existing domain ACLs
    sed -i '/^acl allowed_domains dstdomain/d' "$CONFIG_FILE"

    # Parse comma-separated domains and build ACL lines
    ACLS=""
    OLD_IFS="$IFS"
    IFS=','
    for domain in $ALLOWED_DOMAINS; do
        # Trim whitespace (POSIX-compatible)
        domain=$(echo "$domain" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
        [ -n "$domain" ] && ACLS="${ACLS}acl allowed_domains dstdomain ${domain}
"
    done
    IFS="$OLD_IFS"

    # Write ACLs to a temp file and insert before SSL_ports
    if [ -n "$ACLS" ]; then
        ACLS_FILE=/tmp/acls.conf
        printf '%s' "$ACLS" > "$ACLS_FILE"
        sed -i "/^acl SSL_ports/r $ACLS_FILE" "$CONFIG_FILE"
        # Move ACLs before SSL_ports (r inserts after, so we need to reorder)
        # Actually sed /r/ inserts after the match, which is fine for ACL ordering
        rm -f "$ACLS_FILE"
    fi
fi

# Override DNS if SQUID_DNS is set
if [ -n "${SQUID_DNS:-}" ]; then
    echo "dns_nameservers $SQUID_DNS" >> "$CONFIG_FILE"
fi

exec /usr/sbin/squid -f "$CONFIG_FILE" "$@"
