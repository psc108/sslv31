#!/bin/bash
python3 import_p3.py -i roles.yml -k $OS_AUTH_URL -u $OS_USERNAME -p $OS_PASSWORD -c /etc/keystone/ca.crt