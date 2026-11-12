#!/usr/bin/env bash
# Run as root on a dedicated Ubuntu Droplet after a successful SSH login.
# Root login stays available until the new administrator login is verified.
set -euo pipefail

admin_user="jarvis-admin"
public_key_file="${1:?Pass the path to the administrator public key}"
operator_ipv4="${2:?Pass the verified SSH operator IPv4 address}"
[[ $(id -u) == 0 ]] || { echo "Run as root." >&2; exit 1; }
[[ -r "$public_key_file" ]] || { echo "Public key is unavailable." >&2; exit 1; }
# shellcheck source=/dev/null
. /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 ]] || { echo "This script requires Ubuntu 24.04." >&2; exit 1; }
[[ $(dpkg --print-architecture) == amd64 ]] || { echo "This script requires x64 Ubuntu." >&2; exit 1; }
python3 - "$operator_ipv4" <<'PY'
import ipaddress,sys
address=ipaddress.ip_address(sys.argv[1])
assert address.version == 4 and address.is_global, "Use a verified public IPv4 address."
PY
ssh-keygen -lf "$public_key_file" >/dev/null

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y -o Dpkg::Options::=--force-confold upgrade
apt-get install -y --no-install-recommends ca-certificates curl gnupg ufw fail2ban unattended-upgrades age sudo

if ! id "$admin_user" >/dev/null 2>&1; then
    adduser --disabled-password --gecos '' "$admin_user"
fi
install -d -m 0700 -o "$admin_user" -g "$admin_user" "/home/$admin_user/.ssh"
authorized_keys="/home/$admin_user/.ssh/authorized_keys"
touch "$authorized_keys"
while IFS= read -r public_key || [[ -n "$public_key" ]]; do
    if [[ -n "$public_key" ]] && ! grep -Fqx -- "$public_key" "$authorized_keys"; then
        printf '%s\n' "$public_key" >>"$authorized_keys"
    fi
done <"$public_key_file"
chown "$admin_user:$admin_user" "$authorized_keys"
chmod 0600 "$authorized_keys"
printf '%s ALL=(ALL:ALL) NOPASSWD: ALL\n' "$admin_user" >/etc/sudoers.d/jarvis-admin
chmod 0440 /etc/sudoers.d/jarvis-admin
visudo -cf /etc/sudoers.d/jarvis-admin

cat >/etc/ssh/sshd_config.d/00-jarvis-hardening.conf <<'EOF'
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitEmptyPasswords no
PermitRootLogin prohibit-password
Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com,aes128-gcm@openssh.com
MACs hmac-sha2-512-etm@openssh.com,hmac-sha2-256-etm@openssh.com
X11Forwarding no
AllowAgentForwarding no
AllowTcpForwarding no
PermitTunnel no
GatewayPorts no
MaxAuthTries 3
MaxStartups 10:30:30
LoginGraceTime 30
ClientAliveInterval 300
ClientAliveCountMax 2
EOF
chmod 0644 /etc/ssh/sshd_config.d/00-jarvis-hardening.conf
sshd -t
systemctl reload ssh

ufw default deny incoming
ufw default allow outgoing
ufw allow from "$operator_ipv4" to any port 22 proto tcp comment 'Jarvis administrator'
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

cat >/etc/fail2ban/jail.d/jarvis-sshd.local <<'EOF'
[sshd]
enabled = true
backend = systemd
banaction = ufw
maxretry = 5
findtime = 10m
bantime = 1h
EOF
cat >/etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
cat >/etc/apt/apt.conf.d/52jarvis-security <<'EOF'
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
EOF
systemctl enable --now fail2ban unattended-upgrades

install -m 0755 -d /etc/apt/keyrings
curl --fail --silent --show-error --location https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod 0644 /etc/apt/keyrings/docker.asc
printf 'Types: deb\nURIs: https://download.docker.com/linux/ubuntu\nSuites: noble\nComponents: stable\nSigned-By: /etc/apt/keyrings/docker.asc\nArchitectures: amd64\n' >/etc/apt/sources.list.d/docker.sources
apt-get update
apt-get install -y --no-install-recommends docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
install -d -m 0755 /etc/docker
if [[ ! -e /etc/docker/daemon.json ]]; then
    cat >/etc/docker/daemon.json <<'EOF'
{
  "live-restore": true,
  "no-new-privileges": true,
  "userland-proxy": false,
  "log-driver": "local",
  "log-opts": {"max-size": "10m", "max-file": "3"}
}
EOF
fi
dockerd --validate --config-file=/etc/docker/daemon.json
systemctl enable --now docker
systemctl restart docker

if ! swapon --noheadings --show=NAME | awk '$0 == "/swapfile" {found=1} END {exit !found}'; then
    if [[ ! -e /swapfile ]]; then
        fallocate -l 1G /swapfile
        chmod 0600 /swapfile
        mkswap /swapfile
    fi
    swapon /swapfile
    grep -Eq '^/swapfile[[:space:]]' /etc/fstab || printf '/swapfile none swap sw 0 0\n' >>/etc/fstab
fi
printf 'vm.swappiness=10\n' >/etc/sysctl.d/90-jarvis-memory.conf
sysctl -p /etc/sysctl.d/90-jarvis-memory.conf
install -d -m 0700 /etc/jarvis /var/backups/jarvis
install -d -m 0755 /opt/jarvis/releases
printf 'Host preparation complete. Verify SSH as %s before disabling root login.\n' "$admin_user"
