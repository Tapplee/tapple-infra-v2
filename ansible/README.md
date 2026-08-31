# IDC 단일 노드 bootstrap

Ubuntu 22.04/24.04 x86_64 서버 한 대에 호스트 기본 설정, K3s,
Argo CD, ESO의 AWS bootstrap Secret, root Application을 순서대로 구성한다.
Kubernetes API `6443`은 기본적으로 외부에 열지 않는다. 팀원 kubeconfig가 필요하면
고정 egress 또는 VPN CIDR만 별도 allowlist에 넣는다.
이 전용 노드의 UFW 인바운드 allow 규칙은 플레이북이 전부 소유한다. 방화벽 변경 전에
인바운드 deny/reject, `ufw route allow/limit`, 공백 때문에 안전하게 토큰화할 수 없는 quoted
application-profile 규칙이 있으면 IDC 콘솔에서 먼저 정리하도록 실패한다. 그 뒤 원하는
SSH·API·80/443·K3s 내부 규칙을 추가하고 선언 목록에 없는 과거 인바운드 allow를 제거한다.
아웃바운드 규칙은 건드리지 않는다. API 목록이 비어 있으면 외부 `6443/tcp` 규칙은 0개다.

## 준비

```bash
cd ansible
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

cp inventories/idc/hosts.example.yml inventories/idc/hosts.yml
```

`hosts.yml`에서 다음 값을 검토한다.

- `ansible_host`: IDC 서버 주소
- `ansible_user`: SSH key와 sudo를 사용할 수 있는 계정. 초기 root key 접속도 가능하다.
- `common_admin_ssh_cidrs`: SSH를 허용할 관리자 공인 CIDR
- `common_k3s_api_cidrs`: 선택 사항. 제한된 kubeconfig 접근을 허용할 팀/VPN CIDR
- `bootstrap_confirm`: 모든 값을 확인한 다음에만 `true`

CIDR는 host bit와 IPv6 축약까지 canonical 표기로 쓴다. 예를 들어
`198.51.100.10/24`는 거부되며 `198.51.100.0/24`로 고쳐야 한다. `/0`·`Anywhere`와 public
port 목록의 `22`·`6443`도 호스트를 바꾸기 전 preflight에서 거부한다.
원격 변경 직전에는 호스트가 보는 현재 SSH peer IP가 `common_admin_ssh_cidrs`에 포함됐는지
확인하고, UFW·SSH 적용 후 기존 연결을 끊은 뒤 새 SSH 연결까지 성공해야 계속한다.

`hosts.yml`은 Git에서 제외된다. `host_key_checking`이 켜져 있으므로 첫 실행 전에
직접 SSH로 서버 host key를 확인해 `known_hosts`에 등록한다.

## 검증과 실행

```bash
# YAML, role, module 구문 검증
ansible-playbook --syntax-check playbooks/bootstrap.yml

# 서버에 접속하지 않고 inventory 안전장치만 검사
ansible-playbook --check --tags preflight playbooks/bootstrap.yml

# 실제 bootstrap
ansible-playbook playbooks/bootstrap.yml
```

비밀번호 기반 sudo 계정이라면 마지막 명령에 `--ask-become-pass`를 붙인다.
빈 서버의 전체 bootstrap은 설치 전후 상태가 달라지므로 Ansible check mode로 정확히
예측할 수 없다. 전체 검증 대신 syntax와 preflight 검사를 먼저 실행한다.

정상 종료 조건은 root Application 생성이 아니라 `Synced`와 `Healthy`다. custom health가
모든 child Application과 10개 SecretStore·15개 ExternalSecret의 준비 상태를 전달하므로,
13개 AWS source 중 하나라도 빠지면 최대 30분 뒤 playbook이 실패한다. 실패 상태를 고친 뒤
같은 명령을 다시 실행하면 이어서 수렴한다. 재실행 때도 과거 Healthy 상태를 오인하지 않도록
root에 hard refresh를 요청하고 Argo CD가 그 annotation을 소비한 뒤 상태를 기다린다.

## AWS bootstrap 자격증명

기본 실행은 access key ID와 secret access key를 화면에 표시하지 않고 질문한다.
자동화에서는 실행 환경의 `ESO_AWS_ACCESS_KEY_ID`와
`ESO_AWS_SECRET_ACCESS_KEY`를 controller의 승인된 secret store에서 주입한다.

자격증명을 inventory, vars 파일, 명령행 `--extra-vars`에 평문으로 넣지 않는다.
역할은 값을 `no_log`로 처리하고 `kubectl`의 프로세스 인자가 아닌 stdin으로
전달한다. 생성되는 `external-secrets/aws-bootstrap`은 K3s의 Secret 암호화가
활성화된 것을 확인한 뒤에만 주입된다.
