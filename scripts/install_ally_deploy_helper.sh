#!/bin/sh
# One-time, interactive-root installation only.  Run on the Ally via sudo.
set -eu
umask 077
# SteamOS makes /usr immutable.  Use HDM's existing root-owned /var/lib state
# directory instead of putting a privileged executable in a mutable location.
install -d -m 0700 /var/lib/handheld-dock-mode
install -m 0755 /home/deck/Downloads/ally_hdm_deploy_helper.py /var/lib/handheld-dock-mode/hdm-deploy-plugin
install -m 0644 /home/deck/Downloads/hdm-deploy-public-key.pem /var/lib/handheld-dock-mode/deploy-public-key.pem
cat >/etc/sudoers.d/hdm-deploy-plugin <<'EOF'
# Developer-only HDM package installer.  The binary accepts only signed,
# fixed-name archives in /home/deck, then restarts only the fixed
# Decky plugin loader. It never invokes Gamescope or hardware/session actions.
# Sudo authorizes only the immutable root-owned helper; it intentionally does
# not repeat argument globs because SteamOS sudo parses those globs differently
# from the shell.  The helper itself rejects every argument except an exact
# fixed Downloads ZIP + matching signature, then verifies its public-key
# signature and archive provenance before replacing anything.
deck ALL=(root) NOPASSWD: /var/lib/handheld-dock-mode/hdm-deploy-plugin
EOF
chmod 0440 /etc/sudoers.d/hdm-deploy-plugin
visudo -cf /etc/sudoers.d/hdm-deploy-plugin
echo '{"state":"installed","component":"hdm-deploy-helper"}'
