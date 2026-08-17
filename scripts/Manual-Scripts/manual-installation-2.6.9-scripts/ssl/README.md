# SSL Cert Scripts

## General script output files

* server.key.nopass - unencrypted private key
* server.key - encrypted private key
* server.crt - server certificates
* server.keystore - Java keystore containing private key
* server.truststore - Java trust store with CA certificate
* server.pfx - PKCS12 keystore with private key
* server_chain.crt - server certificate together with all CA certificates

Keep these files safe, they are overwritten on each script run.

## ca/gen_ca_cert.sh

Generates RSA 4096 bits key and self-signed certificate for CA. 
The CA key is used to sign server certificates (below). 
The CA cert should be imported to trust-stores etc. 
because if a client trusts the CA, it trusts certificates signed by the CA.

Usage
```
cd ca
./gen_ca_cert.sh [password]
```

## gen_cert.sh

Generate ECDHE key using secp384r1 curve and certificates signed by the generated CA.

Usage
```
./gen_cert.sh [common_name] [SAN multiple hostnames and/or IPs DNS:...,IP:....] [password]
```

This is the preferred way to build certificates.

## gen_cert_rsa.sh

Generate RSA 4096 bits key and certificates signed by generated CA.

Usage
```
./gen_cert_rsa.sh [common_name] [SAN multiple hostnames and/or IPs DNS:...,IP:....] [password]
```
Use RSA key/cert when ECDHE is not supported e.g. for Rabbit MQ.
