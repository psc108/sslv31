#!/bin/bash

if [ "$#" -ne 4 ]; then
  echo "Generates private key and certificate for a server." >&2
  echo "Note: Previously generated files are replaced by next run." >&2
  echo "Usage: $0 common_name alternative_name key_password ca_password" >&2
  echo "  e.g. with dns name   gen_cert.sh myhost.domain DNS:myhost.domain mypass capass" >&2
  echo "  with ip address gen_cert.sh 1.1.1.1 IP:1.1.1.1 mypass capass" >&2
  echo "Output:" >&2
  echo "   server.key.nopass - unencrypted private key" >&2
  echo "   server.key - encrypted private key" >&2
  echo "   server.crt - server certificate" >&2
  echo "   server.keystore - Java keystore containing private key" >&2
  echo "   server.truststore - Java trust store with CA certificate" >&2
  echo "   server.pfx - PKCS12 keystore with private key" >&2
  echo "   server_chain.crt - server certificate together with all CA certificates" >&2
  exit 1
fi

set -x
rm server*.* -f

# Generate private key
openssl ecparam -genkey -name secp384r1 -noout > server.key.nopass
chmod 600 server.key.nopass
cat server.key.nopass | openssl ec -aes256 -passout "pass:$3" -out server.key

# Generate signing request
export SAN=$2
openssl req -config openssl.cnf -subj "/O=DXC/OU=SSP/CN=$1" -extensions server_cert -key server.key -passin "pass:$3" -new -sha256 -out server.csr

# Sign request by CPI Test CA
rm ca/index.txt
touch ca/index.txt
echo 1000 > ca/serial
openssl ca -verbose -config openssl.cnf -extensions server_cert -days 397 -notext -md sha256 -in server.csr -keyfile ca/ca.key -key "$4" -cert ca/ca.crt -out server.crt -batch

# Create certificate chain
cat server.crt ca/ca.crt > server_chain.crt

# Generate keystore
openssl pkcs12 -export -inkey server.key -in server_chain.crt -out server.pfx -name server -passin "pass:$3" -passout "pass:$3"
keytool -importkeystore -srcstoretype PKCS12 -alias server -srckeystore server.pfx -srcstorepass "$3" -srckeypass "$3" -destkeystore server.keystore -deststorepass "$3" -destkeypass "$3"

# Generate truststore
cp /etc/pki/java/cacerts server.truststore
keytool -storepasswd -keystore server.truststore -storepass changeit -new "$3"
keytool -importcert -file ca/ca.crt -keystore server.truststore -alias 'SSP CA' -storepass "$3" -noprompt


