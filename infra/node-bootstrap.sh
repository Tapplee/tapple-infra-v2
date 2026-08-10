#!/usr/bin/env bash
# Phase 1 — iwinv 노드 기본 세팅 (Ubuntu 22.04, root로 1회 실행)
# 검증: ufw status에서 22/80/443만 개방
set -euo pipefail

ADMIN_IP="${ADMIN_IP:?본인 IP를 ADMIN_IP로 지정 (SSH 허용 대상)}"

# OS 업데이트 + 타임존
apt-get update && apt-get upgrade -y
timedatectl set-timezone Asia/Seoul

# swap 비활성화 (k8s 필수)
swapoff -a
sed -i '/ swap / s/^/#/' /etc/fstab

# 방화벽: 22(본인 IP만) / 80 / 443
ufw default deny incoming
ufw default allow outgoing
ufw allow from "${ADMIN_IP}" to any port 22 proto tcp
ufw allow 80/tcp
ufw allow 443/tcp
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

# TODO(Phase 1): 비루트 배포 사용자 생성

echo "node-bootstrap 완료. ufw status:"
ufw status verbose
