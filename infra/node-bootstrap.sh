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

# TODO(Phase 1): 비루트 배포 사용자 생성 + SSH 하드닝(키 전용, PasswordAuthentication no)

echo "node-bootstrap 완료. ufw status:"
ufw status verbose
