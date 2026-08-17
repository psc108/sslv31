#!/bin/bash
set -euo pipefail

hostnamectl set-hostname "${hostname}"
echo "127.0.0.1 ${hostname}" >> /etc/hosts

%{ if os_type == "ubuntu" }
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-pip openssh-server
%{ endif }

%{ if os_type == "rhel" }
dnf install -y python3 python3-pip openssh-server
systemctl enable --now sshd
%{ endif }

mkdir -p /root/.ssh
chmod 700 /root/.ssh
echo "${ssh_public_key}" >> /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys

touch /tmp/userdata-complete
