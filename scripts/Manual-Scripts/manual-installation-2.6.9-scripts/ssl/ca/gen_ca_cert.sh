#!/bin/bash

if [ "$#" -ne 1 ]; then
  echo "Generates private key and (self-signed) certificate for new Certificate Authority (CA)." >&2
  echo "Note: Previously generated files are replaced by next run." >&2
  echo "Usage: $0 ca_key_password" >&2
  echo "Output:" >&2
  echo "   ca.key - CA private key, keep it safe" >&2
  echo "   ca.crt - CA certificate, to be distributed to clients to trust CA" >&2
  exit 1
fi

set -x
rm ca*.* -f

# Generate private key
openssl genrsa -aes-256-cbc -passout "pass:$1" -out ca.key 4096

# Generate signing request
openssl req -subj "/O=DXC/OU=SSP/CN=DXC SSP Root CA" -key ca.key -passin "pass:$1" -new -out ca.csr

# Self-Sign the request
openssl x509 -signkey ca.key -in ca.csr -passin "pass:$1" -req -days 10950 -out ca.crt

# Remove the signing request
rm ca.csr -f


