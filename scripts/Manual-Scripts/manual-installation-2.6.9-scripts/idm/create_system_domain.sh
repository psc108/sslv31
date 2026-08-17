#!/bin/bash
PASSWORD=${KEYSTONE_SYSTEM_DOMAIN_PASSWORD:-changeit}
python3 import_p3.py -i system_domain.yml -k $OS_AUTH_URL -u $OS_USERNAME -p $OS_PASSWORD -c /etc/keystone/ca.crt -e password,$PASSWORD