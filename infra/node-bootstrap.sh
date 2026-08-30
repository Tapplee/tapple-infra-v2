#!/usr/bin/env bash
# Legacy manual fallback — IDC 노드 기본 세팅 (Ubuntu 22.04/24.04, root로 1회 실행)
# 일반 재구축의 단일 source of truth는 ansible/playbooks/bootstrap.yml이다.
# 검증: ufw status에서 관리자 SSH, 80/443, k3s 내부 CIDR만 허용하고 6443은 공개하지 않는다.
set -euo pipefail

ADMIN_IP="${ADMIN_IP:?본인 IP를 ADMIN_IP로 지정 (SSH 허용 대상)}"
K3S_CLUSTER_CIDR="${K3S_CLUSTER_CIDR:-10.42.0.0/16}"
K3S_SERVICE_CIDR="${K3S_SERVICE_CIDR:-10.43.0.0/16}"

# OS 업데이트 + 타임존
apt-get update && apt-get upgrade -y
apt-get install -y ca-certificates curl ufw
timedatectl set-timezone Asia/Seoul

# swap 비활성화 (k8s 필수)
swapoff -a
sed -i '/ swap / s/^/#/' /etc/fstab

# k3s 커널 선행 조건
cat > /etc/modules-load.d/k3s.conf <<'CONF'
overlay
br_netfilter
CONF
modprobe overlay
modprobe br_netfilter
cat > /etc/sysctl.d/90-k3s.conf <<'CONF'
net.ipv4.ip_forward = 1
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1
CONF
sysctl --system >/dev/null

# 방화벽: 22(본인 IP만) / 80 / 443 / k3s 파드·서비스 CIDR
ufw default deny incoming
ufw default allow outgoing
ufw allow from "${ADMIN_IP}" to any port 22 proto tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow from "${K3S_CLUSTER_CIDR}" to any
ufw allow from "${K3S_SERVICE_CIDR}" to any
ufw --force enable

# SSH 하드닝 — 키 전용
# 주의: cloud-init 이 /etc/ssh/sshd_config.d/50-cloud-init.conf 에 PasswordAuthentication yes 를 박아둔다.
# sshd 는 "먼저 나온 값이 이긴다"라서 99-*.conf 로 덮으면 밀린다 — 그 파일을 직접 고치고 00- 으로 앞당긴다.
sed -i 's/^PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config.d/50-cloud-init.conf 2>/dev/null || true
cat > /etc/ssh/sshd_config.d/00-hardening.conf <<'CONF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
CONF
echo "ssh_pwauth: false" > /etc/cloud/cloud.cfg.d/99-disable-pwauth.cfg   # 재부팅 때 되돌아가지 않게
sshd -t && systemctl reload ssh
sshd -T | grep -E '^(passwordauthentication|permitrootlogin)'

echo "node-bootstrap 완료. ufw status:"
ufw status verbose
