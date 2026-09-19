#!/bin/sh
# One-time interactive-root deploy-authority cutover. This script performs no
# plugin, Gamescope, sleep, display, eGPU, power, or session operation.
set -eu
umask 077

ACTION=${1:-install}
NEW_ROOT=/var/lib/regear/deploy
NEW_HELPER=$NEW_ROOT/regear-deploy-plugin
NEW_MIGRATOR=$NEW_ROOT/regear-migrate-identity
NEW_KEY=$NEW_ROOT/deploy-public-key.pem
NEW_RULE=/etc/sudoers.d/regear-deploy-plugin
STAGED_HELPER=/home/deck/regear-deploy-plugin
STAGED_MIGRATOR=/home/deck/regear-migrate-identity
OLD_ROOT=/var/lib/handheld-dock-mode
OLD_HELPER=$OLD_ROOT/hdm-deploy-plugin
OLD_KEY=$OLD_ROOT/deploy-public-key.pem
OLD_RULE=/etc/sudoers.d/hdm-deploy-plugin
BACKUP=/var/lib/regear/identity-bootstrap-v1

fail() { printf '%s\n' "identity bootstrap refused: $*" >&2; exit 1; }
regular_no_link() { test -f "$1" && test ! -L "$1"; }
root_safe() {
    regular_no_link "$1" || return 1
    test "$(stat -c %u "$1")" = 0 || return 1
    mode=$(stat -c %a "$1")
    test $((0$mode & 022)) -eq 0 || return 1
}
deck_staged_safe() {
    regular_no_link "$1" || return 1
    test "$(stat -c %u "$1")" = 1000 || return 1
    mode=$(stat -c %a "$1")
    test $((0$mode & 022)) -eq 0 || return 1
}

install_authority() {
    test "$(id -u)" = 0 || fail "root is required"
    test ! -e "$BACKUP" && test ! -L "$BACKUP" || fail "bootstrap backup already exists"
    regular_no_link "$STAGED_HELPER" || fail "staged Re-Gear helper is unavailable"
    deck_staged_safe "$STAGED_MIGRATOR" || fail "staged Re-Gear migrator is not exact deck-owned input"
    root_safe "$OLD_HELPER" || fail "former helper is not exact root-owned authority"
    root_safe "$OLD_KEY" || fail "former public key is not exact root-owned authority"
    root_safe "$OLD_RULE" || fail "former sudo policy is not exact root-owned authority"
    test ! -e "$NEW_ROOT" && test ! -L "$NEW_ROOT" || fail "new deploy authority already exists"
    test ! -e "$NEW_RULE" && test ! -L "$NEW_RULE" || fail "new sudo policy already exists"

    install -d -m 0700 /var/lib/regear "$BACKUP"
    install -p -m 0755 "$OLD_HELPER" "$BACKUP/previous-helper"
    install -p -m 0644 "$OLD_KEY" "$BACKUP/previous-public-key.pem"
    install -p -m 0440 "$OLD_RULE" "$BACKUP/previous-sudoers"
    sha256sum "$BACKUP/previous-helper" "$BACKUP/previous-public-key.pem" \
        "$BACKUP/previous-sudoers" >"$BACKUP/previous.sha256"

    install -d -m 0700 "$NEW_ROOT"
    install -m 0755 "$STAGED_HELPER" "$NEW_HELPER"
    install -m 0755 "$STAGED_MIGRATOR" "$NEW_MIGRATOR"
    install -m 0644 "$OLD_KEY" "$NEW_KEY"
    cat >"$NEW_RULE.tmp" <<'EOF'
# Developer-only Re-Gear package installer. The root-owned helper accepts only
# exact signed Re-Gear package names under /home/deck and validates all inputs.
deck ALL=(root) NOPASSWD: /var/lib/regear/deploy/regear-deploy-plugin
deck ALL=(root) NOPASSWD: /var/lib/regear/deploy/regear-migrate-identity status
deck ALL=(root) NOPASSWD: /var/lib/regear/deploy/regear-migrate-identity apply
deck ALL=(root) NOPASSWD: /var/lib/regear/deploy/regear-migrate-identity rollback
EOF
    chmod 0440 "$NEW_RULE.tmp"
    visudo -cf "$NEW_RULE.tmp"
    mv "$NEW_RULE.tmp" "$NEW_RULE"
    "$NEW_HELPER" --self-check >/dev/null
    "$NEW_MIGRATOR" status >/dev/null
    /usr/bin/sudo -u deck /usr/bin/sudo -n "$NEW_HELPER" --self-check >/dev/null
    /usr/bin/sudo -u deck /usr/bin/sudo -n "$NEW_MIGRATOR" status >/dev/null
    sha256sum "$NEW_HELPER" "$NEW_MIGRATOR" "$NEW_KEY" "$NEW_RULE" >"$BACKUP/current.sha256"

    rm -f "$OLD_RULE" "$OLD_HELPER" "$OLD_KEY"
    : >"$BACKUP/COMMITTED"
    printf '%s\n' '{"state":"committed","component":"regear-deploy-authority"}'
}

rollback_authority() {
    test "$(id -u)" = 0 || fail "root is required"
    regular_no_link "$BACKUP/COMMITTED" || fail "committed bootstrap backup is unavailable"
    (cd / && sha256sum -c "$BACKUP/previous.sha256" >/dev/null) || fail "previous authority backup changed"
    (cd / && sha256sum -c "$BACKUP/current.sha256" >/dev/null) || fail "current authority changed after bootstrap"
    test "$(find "$NEW_ROOT" -mindepth 1 -maxdepth 1 -printf '%f\\n' | LC_ALL=C sort)" = "$(printf '%s\\n' deploy-public-key.pem regear-deploy-plugin regear-migrate-identity)" || fail "new deploy authority contains unexpected entries"
    test ! -e "$OLD_HELPER" && test ! -L "$OLD_HELPER" || fail "former helper path is occupied"
    test ! -e "$OLD_KEY" && test ! -L "$OLD_KEY" || fail "former key path is occupied"
    test ! -e "$OLD_RULE" && test ! -L "$OLD_RULE" || fail "former sudo policy path is occupied"

    install -m 0755 "$BACKUP/previous-helper" "$OLD_HELPER"
    install -m 0644 "$BACKUP/previous-public-key.pem" "$OLD_KEY"
    install -m 0440 "$BACKUP/previous-sudoers" "$OLD_RULE.tmp"
    visudo -cf "$OLD_RULE.tmp"
    mv "$OLD_RULE.tmp" "$OLD_RULE"
    rm -f "$NEW_RULE" "$NEW_HELPER" "$NEW_MIGRATOR" "$NEW_KEY"
    rmdir "$NEW_ROOT"
    mv "$BACKUP/COMMITTED" "$BACKUP/ROLLED_BACK"
    printf '%s\n' '{"state":"rolled_back","component":"regear-deploy-authority"}'
}

case "$ACTION" in
    install) install_authority ;;
    rollback) rollback_authority ;;
    *) fail "expected install or rollback" ;;
esac
