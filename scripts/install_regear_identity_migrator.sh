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
BACKUP_PREPARE=/var/lib/regear/.identity-bootstrap-v1.prepare
PHASE=$BACKUP/PHASE
PLUGIN_PARENT=/home/deck/homebrew/plugins
CONTROL_ROOT=/var/lib/regear/control

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
private_directory_safe() {
    test -d "$1" && test ! -L "$1" || return 1
    test "$(stat -c %u "$1")" = 0 || return 1
    test "$(stat -c %a "$1")" = 700 || return 1
}
backup_safe() { private_directory_safe "$BACKUP"; }
sync_backup() { sync -f "$BACKUP"; }
write_phase() {
    if test -e "$PHASE.tmp" || test -L "$PHASE.tmp"; then
        root_safe "$PHASE.tmp" || fail "bootstrap phase temporary is unsafe"
        rm -f "$PHASE.tmp"
    fi
    printf '%s\n' "$1" >"$PHASE.tmp"
    chmod 0600 "$PHASE.tmp"
    mv "$PHASE.tmp" "$PHASE"
    sync_backup
}
verify_signature() {
    authority=$1 payload=$2 signature=$3
    /usr/bin/openssl pkeyutl -verify -pubin -inkey "$authority/previous-public-key.pem" \
        -rawin -in "$payload" -sigfile "$signature" >/dev/null 2>&1 \
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
    authority=$1
    cat >"$authority/current-sudoers" <<'EOF'
# Developer-only Re-Gear package installer. The root-owned helpers accept only
# their fixed signed-package or identity-migration command surfaces.
deck ALL=(root) NOPASSWD: /var/lib/regear/deploy/regear-deploy-plugin
deck ALL=(root) NOPASSWD: /var/lib/regear/deploy/regear-migrate-identity status
deck ALL=(root) NOPASSWD: /var/lib/regear/deploy/regear-migrate-identity apply
deck ALL=(root) NOPASSWD: /var/lib/regear/deploy/regear-migrate-identity rollback
EOF
    chmod 0440 "$authority/current-sudoers"
    visudo -cf "$authority/current-sudoers" >/dev/null
}
expected_payload_names() {
    printf '%s\n' candidate-helper candidate-helper.sig candidate-migrator \
        candidate-migrator.sig candidate.sha256 current-sudoers \
        former-private.names former-private.tar private.sha256 previous-helper \
        previous-public-key.pem previous-sudoers previous.sha256
}
verify_payload() {
    authority=$1
    private_directory_safe "$authority" || fail "bootstrap payload directory is unsafe"
    actual=$(find "$authority" -mindepth 1 -maxdepth 1 -printf '%f\n' | \
        grep -v '^PHASE$' | LC_ALL=C sort)
    expected=$(expected_payload_names | LC_ALL=C sort)
    test "$actual" = "$expected" || fail "bootstrap payload has unexpected or missing entries"
    (cd "$authority" && sha256sum -c previous.sha256 candidate.sha256 private.sha256 >/dev/null) \
        || fail "bootstrap backup changed"
    verify_signature "$authority" "$authority/candidate-helper" "$authority/candidate-helper.sig"
    verify_signature "$authority" "$authority/candidate-migrator" "$authority/candidate-migrator.sig"
    visudo -cf "$authority/current-sudoers" >/dev/null
    /usr/bin/tar --list --file="$authority/former-private.tar" >/dev/null
}
verify_backup() {
    verify_payload "$BACKUP"
    regular_no_link "$PHASE" || fail "bootstrap phase is unavailable"
}
discover_former_private() {
    destination=$1
    test -d "$PLUGIN_PARENT" && test ! -L "$PLUGIN_PARENT" \
        || fail "plugin parent is unsafe"
    find "$PLUGIN_PARENT" -mindepth 1 -maxdepth 1 \
        \( -name '.hdm-deploy-backups' -o -name '.hdm-staging-*' \) \
        -printf '%f\n' | LC_ALL=C sort >"$destination"
    while IFS= read -r name; do
        case "$name" in
            .hdm-deploy-backups|.hdm-staging-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]) ;;
            *) fail "unexpected former private directory name" ;;
        esac
        path=$PLUGIN_PARENT/$name
        test -d "$path" && test ! -L "$path" \
            || fail "former private path is not a real directory"
        unexpected=$(/usr/bin/find "$path" -xdev ! -type d ! -type f -print -quit)
        test -z "$unexpected" || fail "former private tree contains a link or special file"
    done <"$destination"
}
archive_former_private() {
    authority=$1
    discover_former_private "$authority/former-private.names"
    /usr/bin/tar --create --file="$authority/former-private.tar" \
        --directory="$PLUGIN_PARENT" --numeric-owner --acls --xattrs \
        --verbatim-files-from --files-from="$authority/former-private.names"
    (cd "$authority" && sha256sum former-private.names former-private.tar >private.sha256)
    compare_all_former_private "$authority"
}
compare_one_former_private() {
    authority=$1 name=$2
    path=$PLUGIN_PARENT/$name
    test -d "$path" && test ! -L "$path" \
        || fail "former private directory is absent or unsafe: $name"
    /usr/bin/tar --compare --file="$authority/former-private.tar" \
        --directory="$PLUGIN_PARENT" --numeric-owner --acls --xattrs "$name" >/dev/null \
        || fail "former private directory changed: $name"
}
compare_all_former_private() {
    authority=$1
    current=$authority/former-private.current
    test ! -e "$current" && test ! -L "$current" \
        || fail "former private inventory temporary is occupied"
    discover_former_private "$current"
    cmp -s "$authority/former-private.names" "$current" \
        || fail "former private directory names changed"
    rm -f "$current"
    while IFS= read -r name; do
        compare_one_former_private "$authority" "$name"
    done <"$authority/former-private.names"
}
verify_former_private_subset() {
    authority=$1
    current=$authority/former-private.current
    test ! -e "$current" && test ! -L "$current" \
        || fail "former private inventory temporary is occupied"
    discover_former_private "$current"
    while IFS= read -r name; do
        grep -F -x "$name" "$authority/former-private.names" >/dev/null \
            || fail "unexpected former private directory appeared"
        compare_one_former_private "$authority" "$name"
    done <"$current"
    rm -f "$current"
}
retire_former_private() {
    verify_former_private_subset "$BACKUP"
    while IFS= read -r name; do
        path=$PLUGIN_PARENT/$name
        if test -e "$path" || test -L "$path"; then
            compare_one_former_private "$BACKUP" "$name"
            rm -rf -- "$path"
        fi
    done <"$BACKUP/former-private.names"
    sync -f "$PLUGIN_PARENT"
    discover_former_private "$BACKUP/former-private.current"
    test ! -s "$BACKUP/former-private.current" \
        || fail "former private directories remain after retirement"
    rm -f "$BACKUP/former-private.current"
}
restore_former_private() {
    verify_former_private_subset "$BACKUP"
    while IFS= read -r name; do
        path=$PLUGIN_PARENT/$name
        if test -e "$path" || test -L "$path"; then
            compare_one_former_private "$BACKUP" "$name"
        else
            /usr/bin/tar --extract --file="$BACKUP/former-private.tar" \
                --directory="$PLUGIN_PARENT" --numeric-owner --same-owner \
                --same-permissions --acls --xattrs "$name"
            compare_one_former_private "$BACKUP" "$name"
        fi
    done <"$BACKUP/former-private.names"
    sync -f "$PLUGIN_PARENT"
    compare_all_former_private "$BACKUP"
}
clear_prepare() {
    if test -e "$BACKUP_PREPARE" || test -L "$BACKUP_PREPARE"; then
        private_directory_safe "$BACKUP_PREPARE" \
            || fail "bootstrap prepare directory is unsafe"
        rm -rf -- "$BACKUP_PREPARE"
        sync -f "$(dirname "$BACKUP_PREPARE")"
    fi
}
clear_backup_temporaries() {
    for temporary in "$PHASE.tmp" "$BACKUP/former-private.current"; do
        if test -e "$temporary" || test -L "$temporary"; then
            root_safe "$temporary" || fail "bootstrap temporary is unsafe"
            rm -f "$temporary"
        fi
    done
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

    test ! -L /var/lib/regear || fail "Re-Gear authority parent is unsafe"
    install -d -m 0700 /var/lib/regear
    private_directory_safe /var/lib/regear || fail "Re-Gear authority parent is unsafe"
    clear_prepare
    mkdir -m 0700 "$BACKUP_PREPARE"
    install -p -m 0755 "$OLD_HELPER" "$BACKUP_PREPARE/previous-helper"
    install -p -m 0644 "$OLD_KEY" "$BACKUP_PREPARE/previous-public-key.pem"
    install -p -m 0440 "$OLD_RULE" "$BACKUP_PREPARE/previous-sudoers"
    install -m 0755 "$STAGED_HELPER" "$BACKUP_PREPARE/candidate-helper"
    install -m 0644 "$STAGED_HELPER_SIG" "$BACKUP_PREPARE/candidate-helper.sig"
    install -m 0755 "$STAGED_MIGRATOR" "$BACKUP_PREPARE/candidate-migrator"
    install -m 0644 "$STAGED_MIGRATOR_SIG" "$BACKUP_PREPARE/candidate-migrator.sig"
    (cd "$BACKUP_PREPARE" && sha256sum previous-helper previous-public-key.pem previous-sudoers >previous.sha256)
    (cd "$BACKUP_PREPARE" && sha256sum candidate-helper candidate-helper.sig \
        candidate-migrator candidate-migrator.sig >candidate.sha256)
    write_rule "$BACKUP_PREPARE"
    archive_former_private "$BACKUP_PREPARE"
    verify_payload "$BACKUP_PREPARE"
    sync -f "$BACKUP_PREPARE"
    test ! -e "$BACKUP" && test ! -L "$BACKUP" \
        || fail "bootstrap backup destination is occupied"
    mv "$BACKUP_PREPARE" "$BACKUP"
    sync -f /var/lib/regear
    write_phase PREPARED
}
publish_current() {
    install -d -m 0700 "$NEW_ROOT"
    install_if_absent_or_exact "$BACKUP/candidate-helper" "$NEW_HELPER" 0755
    install_if_absent_or_exact "$BACKUP/candidate-migrator" "$NEW_MIGRATOR" 0755
    install_if_absent_or_exact "$BACKUP/previous-public-key.pem" "$NEW_KEY" 0644
    install_if_absent_or_exact "$BACKUP/current-sudoers" "$NEW_RULE" 0440
    verify_current_authority
    write_phase CURRENT_VERIFIED
}
verify_current_authority() {
    private_directory_safe "$NEW_ROOT" || fail "current deploy authority root is unsafe"
    for pair in \
        "$BACKUP/candidate-helper:$NEW_HELPER" \
        "$BACKUP/candidate-migrator:$NEW_MIGRATOR" \
        "$BACKUP/previous-public-key.pem:$NEW_KEY" \
        "$BACKUP/current-sudoers:$NEW_RULE"; do
        source=${pair%%:*}
        destination=${pair#*:}
        root_safe "$destination" && cmp -s "$source" "$destination" \
            || fail "current deploy authority changed: $destination"
    done
    visudo -cf "$NEW_RULE" >/dev/null
    "$NEW_HELPER" --self-check >/dev/null
    "$NEW_MIGRATOR" status >/dev/null
    /usr/bin/sudo -u deck /usr/bin/sudo -n "$NEW_HELPER" --self-check >/dev/null
    /usr/bin/sudo -u deck /usr/bin/sudo -n "$NEW_MIGRATOR" status >/dev/null
}
verify_committed_authority() {
    verify_current_authority
    test ! -e "$OLD_HELPER" && test ! -L "$OLD_HELPER" \
        || fail "former helper returned after bootstrap commit"
    test ! -e "$OLD_KEY" && test ! -L "$OLD_KEY" \
        || fail "former key returned after bootstrap commit"
    test ! -e "$OLD_RULE" && test ! -L "$OLD_RULE" \
        || fail "former sudo policy returned after bootstrap commit"
    former=$(find "$PLUGIN_PARENT" -mindepth 1 -maxdepth 1 \
        \( -name '.hdm-deploy-backups' -o -name '.hdm-staging-*' \) -print -quit)
    test -z "$former" || fail "former private directory returned after bootstrap commit"
}
retire_former() {
    write_phase RETIRING_FORMER
    same_or_absent "$BACKUP/previous-helper" "$OLD_HELPER" || fail "former helper changed"
    same_or_absent "$BACKUP/previous-public-key.pem" "$OLD_KEY" || fail "former key changed"
    same_or_absent "$BACKUP/previous-sudoers" "$OLD_RULE" || fail "former sudo policy changed"
    retire_former_private
    rm -f "$OLD_RULE" "$OLD_HELPER" "$OLD_KEY"
    write_phase OLD_RETIRED
    write_phase COMMITTED
}
install_authority() {
    test "$(id -u)" = 0 || fail "root is required"
    if test ! -e "$BACKUP" && test ! -L "$BACKUP"; then prepare; fi
    clear_backup_temporaries
    if test ! -e "$PHASE" && test ! -L "$PHASE"; then
        verify_payload "$BACKUP"
        compare_all_former_private "$BACKUP"
        write_phase PREPARED
    fi
    verify_backup
    clear_prepare
    state=$(cat "$PHASE")
    case "$state" in
        PREPARED) publish_current; retire_former ;;
        CURRENT_VERIFIED) publish_current; retire_former ;;
        RETIRING_FORMER) publish_current; retire_former ;;
        OLD_RETIRED) publish_current; retire_former ;;
        COMMITTED) verify_committed_authority ;;
        ROLLED_BACK) fail "bootstrap was rolled back" ;;
        *) fail "unknown bootstrap phase" ;;
    esac
    printf '%s\n' '{"state":"committed","component":"regear-deploy-authority"}'
}
restore_former() {
    test ! -L "$OLD_ROOT" || fail "former authority root is unsafe"
    mkdir -p "$OLD_ROOT"
    restore_former_private
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
require_identity_rollback_first() {
    test ! -e "$CONTROL_ROOT" && test ! -L "$CONTROL_ROOT" \
        || fail "current control identity is still active; run the current Re-Gear migrator rollback first"
    status=$("$BACKUP/candidate-migrator" status) \
        || fail "identity migration status is unavailable; bootstrap rollback is refused"
    printf '%s' "$status" | /usr/bin/python3 -c '
import json, sys
try:
    value = json.load(sys.stdin)
    locations = value["locations"]
    dropin = value["gamescope_dropin"]
    safe = (
        isinstance(locations, dict)
        and all(state in {"old_only", "neither"} for state in locations.values())
        and value.get("journal_phase") in {None, "rolled_back"}
        and value.get("combined_journal_phase") in {None, "rolled_back"}
        and isinstance(dropin, dict)
        and dropin.get("current") == "absent"
        and dropin.get("former") in {"absent", "former"}
        and dropin.get("journal_phase") in {None, "rolled_back"}
    )
except (KeyError, TypeError, ValueError, json.JSONDecodeError):
    safe = False
raise SystemExit(0 if safe else 1)
' || fail "current identity migration is still applied; run the current Re-Gear migrator rollback first"
}
rollback_authority() {
    test "$(id -u)" = 0 || fail "root is required"
    clear_backup_temporaries
    verify_backup
    state=$(cat "$PHASE")
    case "$state" in
        PREPARED|CURRENT_VERIFIED|RETIRING_FORMER|OLD_RETIRED|COMMITTED) ;;
        ROLLED_BACK) printf '%s\n' '{"state":"rolled_back","component":"regear-deploy-authority"}'; return ;;
        *) fail "unknown bootstrap phase" ;;
    esac
    require_identity_rollback_first
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
