#!/bin/sh
# One-time, interactive-root installation only.  Run on the Ally via sudo.
set -eu
umask 077
# SteamOS makes /usr immutable. Keep installer authority separate from runtime
# recovery state and install only fixed, root-owned Re-Gear paths.
install -d -m 0700 /var/lib/regear /var/lib/regear/deploy
install -m 0755 /home/deck/regear-deploy-plugin /var/lib/regear/deploy/regear-deploy-plugin
install -m 0644 /home/deck/regear-deploy-public-key.pem /var/lib/regear/deploy/deploy-public-key.pem
cat >/etc/sudoers.d/regear-deploy-plugin.tmp <<'EOF'
# Developer-only Re-Gear package installer.  The binary accepts only signed,
# fixed-name archives in /home/deck, then restarts only the fixed
# Decky plugin loader. It never invokes Gamescope or hardware/session actions.
# Sudo authorizes only the immutable root-owned helper; it intentionally does
# not repeat argument globs because SteamOS sudo parses those globs differently
# from the shell.  The helper itself rejects every argument except an exact
# fixed `/home/deck/` ZIP + matching signature, then verifies its public-key
# signature and archive provenance before replacing anything.
deck ALL=(root) NOPASSWD: /var/lib/regear/deploy/regear-deploy-plugin
EOF
chmod 0440 /etc/sudoers.d/regear-deploy-plugin.tmp
visudo -cf /etc/sudoers.d/regear-deploy-plugin.tmp
mv /etc/sudoers.d/regear-deploy-plugin.tmp /etc/sudoers.d/regear-deploy-plugin
/var/lib/regear/deploy/regear-deploy-plugin --self-check
