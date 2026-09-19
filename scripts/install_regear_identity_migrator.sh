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
STAGED_HELPER_SIG=/home/deck/regear-deploy-plugin.sig
STAGED_MIGRATOR=/home/deck/regear-migrate-identity
STAGED_MIGRATOR_SIG=/home/deck/regear-migrate-identity.sig
OLD_ROOT=/var/lib/handheld-dock-mode
OLD_HELPER=$OLD_ROOT/hdm-deploy-plugin
OLD_KEY=$OLD_ROOT/deploy-public-key.pem
OLD_RULE=/etc/sudoers.d/hdm-deploy-plugin
BACKUP=/var/lib/regear/identity-bootstrap-v1
PHASE=$BACKUP/PHASE

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
backup_safe() {
    test -d "$BACKUP" && test ! -L "$BACKUP" || return 1
    test "$(stat -c %u "$BACKUP")" = 0 || return 1
    test "$(stat -c %a "$BACKUP")" = 700 || return 1
}
sync_backup() { sync -f "$BACKUP"; }
write_phase() {
    printf '%s\n' "$1" >"$PHASE.tmp"
    chmod 0600 "$PHASE.tmp"
    mv "$PHASE.tmp" "$PHASE"
    sync_backup
}
verify_signature() {
    /usr/bin/openssl pkeyutl -verify -pubin -inkey "$BACKUP/previous-public-key.pem" \
        -rawin -in "$1" -sigfile "$2" >/dev/null 2>&1 \
        || fail "candidate signature verification failed"
}
same_or_absent() {
    test ! -e "$2" && test ! -L "$2" && return 0
    regular_no_link "$2" && cmp -s "$1" "$2"
}
install_if_absent_or_exact() {
    source=$1 destination=$2 mode=$3
    same_or_absent "$source" "$destination" || fail "authority destination changed: $destination"
    if test ! -e "$destination"; then install -m "$mode" "$source" "$destination"; fi
}
write_rule() {
    cat >"$BACKUP/current-sudoers" <<'EOF'
# Developer-only Re-Gear package installer. The root-owned helpers accept only
# their fixed signed-package or identity-migration command surfaces.
deck ALL=(root) NOPASSWD: /var/lib/regear/deploy/regear-deploy-plugin
deck ALL=(root) NOPASSWD: /var/lib/regear/deploy/regear-migrate-identity status
deck ALL=(root) NOPASSWD: /var/lib/regear/deploy/regear-migrate-identity apply
deck ALL=(root) NOPASSWD: /var/lib/regear/deploy/regear-migrate-identity rollback
EOF
    chmod 0440 "$BACKUP/current-sudoers"
    visudo -cf "$BACKUP/current-sudoers" >/dev/null
}
verify_backup() {
    backup_safe || fail "bootstrap backup is unsafe"
    (cd "$BACKUP" && sha256sum -c previous.sha256 candidate.sha256 >/dev/null) \
        || fail "bootstrap backup changed"
    verify_signature "$BACKUP/candidate-helper" "$BACKUP/candidate-helper.sig"
    verify_signature "$BACKUP/candidate-migrator" "$BACKUP/candidate-migrator.sig"
    regular_no_link "$PHASE" || fail "bootstrap phase is unavailable"
}
prepare() {
    deck_staged_safe "$STAGED_HELPER" || fail "staged Re-Gear helper is unsafe"
    deck_staged_safe "$STAGED_HELPER_SIG" || fail "staged helper signature is unsafe"
    deck_staged_safe "$STAGED_MIGRATOR" || fail "staged Re-Gear migrator is unsafe"
    deck_staged_safe "$STAGED_MIGRATOR_SIG" || fail "staged migrator signature is unsafe"
    root_safe "$OLD_HELPER" || fail "former helper is not exact root-owned authority"
    root_safe "$OLD_KEY" || fail "former public key is not exact root-owned authority"
    root_safe "$OLD_RULE" || fail "former sudo policy is not exact root-owned authority"
    test ! -e "$NEW_ROOT" && test ! -L "$NEW_ROOT" || fail "new deploy authority already exists"
    test ! -e "$NEW_RULE" && test ! -L "$NEW_RULE" || fail "new sudo policy already exists"

    install -d -m 0700 /var/lib/regear "$BACKUP"
    install -p -m 0755 "$OLD_HELPER" "$BACKUP/previous-helper"
    install -p -m 0644 "$OLD_KEY" "$BACKUP/previous-public-key.pem"
    install -p -m 0440 "$OLD_RULE" "$BACKUP/previous-sudoers"
    install -m 0755 "$STAGED_HELPER" "$BACKUP/candidate-helper"
    install -m 0644 "$STAGED_HELPER_SIG" "$BACKUP/candidate-helper.sig"
    install -m 0755 "$STAGED_MIGRATOR" "$BACKUP/candidate-migrator"
    install -m 0644 "$STAGED_MIGRATOR_SIG" "$BACKUP/candidate-migrator.sig"
    (cd "$BACKUP" && sha256sum previous-helper previous-public-key.pem previous-sudoers >previous.sha256)
    (cd "$BACKUP" && sha256sum candidate-helper candidate-helper.sig \
        candidate-migrator candidate-migrator.sig >candidate.sha256)
    write_rule
    verify_signature "$BACKUP/candidate-helper" "$BACKUP/candidate-helper.sig"
    verify_signature "$BACKUP/candidate-migrator" "$BACKUP/candidate-migrator.sig"
    write_phase PREPARED
}
publish_current() {
    install -d -m 0700 "$NEW_ROOT"
    install_if_absent_or_exact "$BACKUP/candidate-helper" "$NEW_HELPER" 0755
    install_if_absent_or_exact "$BACKUP/candidate-migrator" "$NEW_MIGRATOR" 0755
    install_if_absent_or_exact "$BACKUP/previous-public-key.pem" "$NEW_KEY" 0644
    install_if_absent_or_exact "$BACKUP/current-sudoers" "$NEW_RULE" 0440
    visudo -cf "$NEW_RULE" >/dev/null
    "$NEW_HELPER" --self-check >/dev/null
    "$NEW_MIGRATOR" status >/dev/null
    /usr/bin/sudo -u deck /usr/bin/sudo -n "$NEW_HELPER" --self-check >/dev/null
    /usr/bin/sudo -u deck /usr/bin/sudo -n "$NEW_MIGRATOR" status >/dev/null
    write_phase CURRENT_VERIFIED
}
retire_former() {
    same_or_absent "$BACKUP/previous-helper" "$OLD_HELPER" || fail "former helper changed"
    same_or_absent "$BACKUP/previous-public-key.pem" "$OLD_KEY" || fail "former key changed"
    same_or_absent "$BACKUP/previous-sudoers" "$OLD_RULE" || fail "former sudo policy changed"
    rm -f "$OLD_RULE" "$OLD_HELPER" "$OLD_KEY"
    write_phase OLD_RETIRED
    write_phase COMMITTED
}
install_authority() {
    test "$(id -u)" = 0 || fail "root is required"
    if test ! -e "$BACKUP" && test ! -L "$BACKUP"; then prepare; fi
    verify_backup
    state=$(cat "$PHASE")
    case "$state" in
        PREPARED) publish_current; retire_former ;;
        CURRENT_VERIFIED) publish_current; retire_former ;;
        OLD_RETIRED) publish_current; retire_former ;;
        COMMITTED) publish_current ;;
        ROLLED_BACK) fail "bootstrap was rolled back" ;;
        *) fail "unknown bootstrap phase" ;;
    esac
    printf '%s\n' '{"state":"committed","component":"regear-deploy-authority"}'
}
restore_former() {
    mkdir -p "$OLD_ROOT"
    test ! -L "$OLD_ROOT" || fail "former authority root is unsafe"
    install_if_absent_or_exact "$BACKUP/previous-helper" "$OLD_HELPER" 0755
    install_if_absent_or_exact "$BACKUP/previous-public-key.pem" "$OLD_KEY" 0644
    install_if_absent_or_exact "$BACKUP/previous-sudoers" "$OLD_RULE" 0440
    visudo -cf "$OLD_RULE" >/dev/null
}
remove_current() {
    same_or_absent "$BACKUP/candidate-helper" "$NEW_HELPER" || fail "current helper changed"
    same_or_absent "$BACKUP/candidate-migrator" "$NEW_MIGRATOR" || fail "current migrator changed"
    same_or_absent "$BACKUP/previous-public-key.pem" "$NEW_KEY" || fail "current key changed"
    same_or_absent "$BACKUP/current-sudoers" "$NEW_RULE" || fail "current sudo policy changed"
    rm -f "$NEW_RULE" "$NEW_HELPER" "$NEW_MIGRATOR" "$NEW_KEY"
    if test -d "$NEW_ROOT" && test ! -L "$NEW_ROOT"; then rmdir "$NEW_ROOT"; fi
}
rollback_authority() {
    test "$(id -u)" = 0 || fail "root is required"
    verify_backup
    state=$(cat "$PHASE")
    case "$state" in
        PREPARED|CURRENT_VERIFIED|OLD_RETIRED|COMMITTED) ;;
        ROLLED_BACK) printf '%s\n' '{"state":"rolled_back","component":"regear-deploy-authority"}'; return ;;
        *) fail "unknown bootstrap phase" ;;
    esac
    restore_former
    remove_current
    write_phase ROLLED_BACK
    printf '%s\n' '{"state":"rolled_back","component":"regear-deploy-authority"}'
}

case "$ACTION" in
    install) install_authority ;;
    rollback) rollback_authority ;;
    *) fail "expected install or rollback" ;;
esac
