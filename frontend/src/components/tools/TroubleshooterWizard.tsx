import { useState } from 'react'
import CopyButton from '@/components/CopyButton'

interface Cause {
  likely: 'high' | 'medium' | 'low'
  text: string
  check: string
  fix: string
}

interface Scenario {
  id: string
  label: string
  icon: string
  meaning: string
  causes: Cause[]
  tools: string[]
  helpSection: string
  commands: string[]
}

const scenarios: Scenario[] = [
  {
    id: 'connection_refused',
    label: 'Connection refused / timed out',
    icon: '🔌',
    meaning: 'The client cannot reach the server at all. This is a network/service problem, not a certificate problem.',
    causes: [
      { likely: 'high', text: 'Service not running or listening on wrong port', check: 'systemctl status <service>', fix: 'Start the service; check it binds to the correct port' },
      { likely: 'high', text: 'Firewall blocking the port', check: 'ufw status / iptables -L -n', fix: 'Allow the port: ufw allow <port>/tcp' },
      { likely: 'medium', text: 'Service listening on localhost only (127.0.0.1)', check: 'ss -tlnp | grep <port>', fix: 'Bind to 0.0.0.0 or the correct interface' },
      { likely: 'low', text: 'DNS resolving to wrong IP', check: 'dig <hostname> / nslookup <hostname>', fix: 'Fix DNS record or use IP directly to test' },
    ],
    tools: ['remote', 'conntest'],
    helpSection: '14',
    commands: [
      'ss -tlnp | grep <port>',
      'curl -v https://<hostname>:<port>/',
      'openssl s_client -connect <hostname>:<port>',
      'telnet <hostname> <port>',
    ],
  },
  {
    id: 'cert_not_trusted',
    label: 'Certificate not trusted (PKIX path building failed)',
    icon: '🚫',
    meaning: 'The client does not trust the CA that signed the server certificate. The chain cannot be verified against any known root.',
    causes: [
      { likely: 'high', text: 'Internal CA not imported into client trust store', check: 'keytool -list -keystore <truststore> | grep <ca-alias>', fix: 'Import root-ca.pem into the client truststore or system CA store' },
      { likely: 'high', text: 'Java using default cacerts (missing your CA)', check: 'java -Djavax.net.debug=ssl:trustmanager ... 2>&1 | grep "adding as trusted"', fix: 'Import CA into $JAVA_HOME/lib/security/cacerts or set -Djavax.net.ssl.trustStore' },
      { likely: 'medium', text: 'Custom truststore missing public CAs', check: 'keytool -list -keystore truststore.p12 | wc -l', fix: 'Merge your CA with system cacerts using the Merge TrustStores tool' },
      { likely: 'medium', text: 'Intermediate CA missing from server chain', check: 'openssl s_client -connect <host>:<port> -showcerts', fix: 'Configure server to send full chain (use chain.pem not cert.pem)' },
      { likely: 'low', text: 'Wrong truststore file referenced', check: 'Check -Djavax.net.ssl.trustStore path exists and is readable', fix: 'Verify path and file permissions' },
    ],
    tools: ['conntest', 'chainexpiry', 'verify', 'merger'],
    helpSection: '17',
    commands: [
      'openssl s_client -connect <host>:<port> -CAfile root-ca.pem',
      'keytool -list -keystore $JAVA_HOME/lib/security/cacerts -storepass changeit | grep -i <ca-name>',
      'java -Djavax.net.debug=ssl:trustmanager -jar app.jar 2>&1 | grep -A5 "found trusted"',
      'openssl verify -CAfile root-ca.pem -untrusted intermediate.pem cert.pem',
    ],
  },
  {
    id: 'hostname_mismatch',
    label: 'Hostname verification failed',
    icon: '🏷️',
    meaning: 'The certificate is trusted but does not cover the hostname being connected to. The SANs in the cert do not match.',
    causes: [
      { likely: 'high', text: 'Certificate missing a DNS SAN for this hostname', check: 'openssl x509 -in cert.pem -noout -ext subjectAltName', fix: 'Re-issue certificate with the correct hostname as a DNS SAN' },
      { likely: 'high', text: 'Connecting by IP but cert only has DNS SANs', check: 'Check if cert has IP SAN entries', fix: 'Add an IP SAN (IP:x.x.x.x) to the certificate, or connect by hostname' },
      { likely: 'medium', text: 'CN set but no SANs (Java/modern browsers ignore CN)', check: 'openssl x509 -in cert.pem -noout -text | grep -A1 "Subject Alternative"', fix: 'Re-issue with SANs — CN alone is not sufficient' },
      { likely: 'low', text: 'Wildcard cert not matching (*.example.com doesn\'t match example.com)', check: 'Compare exact SAN values against the URL being accessed', fix: 'Add the bare domain as an additional SAN alongside the wildcard' },
    ],
    tools: ['remote', 'decode', 'compat'],
    helpSection: '17',
    commands: [
      'openssl x509 -in cert.pem -noout -ext subjectAltName',
      'openssl s_client -connect <host>:<port> -servername <hostname> 2>/dev/null | openssl x509 -noout -ext subjectAltName',
      'curl -v --resolve <hostname>:<port>:<ip> https://<hostname>:<port>/',
    ],
  },
  {
    id: 'cert_expired',
    label: 'Certificate expired',
    icon: '⏰',
    meaning: 'The certificate (or one of the intermediates in the chain) has passed its Not After date.',
    causes: [
      { likely: 'high', text: 'Leaf certificate expired — needs renewal', check: 'openssl x509 -in cert.pem -enddate -noout', fix: 'Issue a new certificate and deploy it' },
      { likely: 'medium', text: 'Intermediate CA expired (invisible — leaf looks fine)', check: 'openssl s_client -connect <host>:<port> -showcerts 2>/dev/null | openssl x509 -noout -dates', fix: 'Check ALL certificates in chain — use Chain Expiry tool' },
      { likely: 'low', text: 'Server clock wrong (cert appears expired but isn\'t)', check: 'date; openssl x509 -in cert.pem -dates -noout', fix: 'Sync system clock: timedatectl set-ntp true' },
    ],
    tools: ['chainexpiry', 'remote', 'decode'],
    helpSection: '14',
    commands: [
      'openssl x509 -in cert.pem -checkend 0 -noout && echo "Valid" || echo "EXPIRED"',
      'openssl x509 -in cert.pem -enddate -noout',
      'echo | openssl s_client -connect <host>:<port> 2>/dev/null | openssl x509 -noout -dates',
    ],
  },
  {
    id: 'key_mismatch',
    label: 'Key does not match certificate',
    icon: '🔑',
    meaning: 'The private key file and the certificate file are not a matching pair. They were generated separately.',
    causes: [
      { likely: 'high', text: 'Wrong key file deployed alongside the certificate', check: 'Compare modulus of cert and key (see commands below)', fix: 'Find the correct key that was generated with this cert\'s CSR' },
      { likely: 'medium', text: 'Certificate was re-issued but old key is still deployed', check: 'Check certificate serial vs what you expected', fix: 'Deploy the key that matches the new certificate' },
      { likely: 'low', text: 'Key file corrupted or truncated', check: 'openssl rsa -in key.pem -check -noout', fix: 'Re-download or regenerate key + cert pair' },
    ],
    tools: ['keymatch'],
    helpSection: '14',
    commands: [
      'openssl x509 -noout -modulus -in cert.pem | openssl md5',
      'openssl rsa -noout -modulus -in key.pem | openssl md5',
      '# Both MD5 values MUST match. If they differ, wrong key.',
      'openssl rsa -in key.pem -check -noout',
    ],
  },
  {
    id: 'client_cert_required',
    label: 'Client certificate required (mTLS)',
    icon: '🤝',
    meaning: 'The server requires the client to present a certificate for authentication, but none was provided or it was rejected.',
    causes: [
      { likely: 'high', text: 'No client certificate configured', check: 'Check if -Djavax.net.ssl.keyStore is set', fix: 'Configure a keystore containing the client cert + key' },
      { likely: 'medium', text: 'Client cert not signed by a CA the server trusts', check: 'Check server logs for "unknown_ca" or "certificate_unknown"', fix: 'Import the client cert\'s CA into the server\'s truststore' },
      { likely: 'medium', text: 'Client cert expired', check: 'openssl x509 -in client-cert.pem -dates -noout', fix: 'Renew the client certificate' },
      { likely: 'low', text: 'Client cert has wrong EKU (missing clientAuth)', check: 'openssl x509 -in client-cert.pem -noout -ext extendedKeyUsage', fix: 'Re-issue with Client (mTLS) profile' },
    ],
    tools: ['conntest', 'decode', 'compat'],
    helpSection: '17',
    commands: [
      'openssl s_client -connect <host>:<port> -cert client.pem -key client-key.pem -CAfile root-ca.pem',
      'openssl x509 -in client-cert.pem -noout -ext extendedKeyUsage',
      'java -Djavax.net.debug=ssl:keymanager -jar app.jar 2>&1 | grep "found key"',
    ],
  },
  {
    id: 'handshake_failure',
    label: 'TLS handshake failure (protocol/cipher)',
    icon: '🤖',
    meaning: 'Client and server cannot agree on a TLS version or cipher suite. No certificate is exchanged because the handshake fails earlier.',
    causes: [
      { likely: 'high', text: 'Client using TLS 1.0/1.1 but server requires 1.2+', check: 'openssl s_client -connect <host>:<port> -tls1_2', fix: 'Upgrade client: -Dhttps.protocols=TLSv1.2,TLSv1.3' },
      { likely: 'medium', text: 'No overlapping cipher suites', check: 'openssl s_client -connect <host>:<port> -cipher HIGH', fix: 'Check server cipher config; use HIGH:!aNULL:!MD5' },
      { likely: 'low', text: 'SNI not sent (server returns wrong cert/rejects)', check: 'openssl s_client -connect <host>:<port> -servername <hostname>', fix: 'Ensure client sends SNI; connect by hostname not IP' },
    ],
    tools: ['conntest', 'remote'],
    helpSection: '17',
    commands: [
      'openssl s_client -connect <host>:<port> -tls1_2 2>&1 | grep "Protocol\\|Cipher"',
      'openssl s_client -connect <host>:<port> -tls1_3 2>&1 | grep "Protocol\\|Cipher"',
      'openssl ciphers -v HIGH | head -20',
      'java -Djavax.net.debug=ssl:handshake -jar app.jar 2>&1 | grep -i "protocol\\|cipher\\|error"',
    ],
  },
  {
    id: 'invalid_keystore',
    label: 'Invalid keystore format (Java)',
    icon: '☕',
    meaning: 'Java cannot read the keystore or truststore file. Usually a format mismatch (JKS vs PKCS12) or wrong password.',
    causes: [
      { likely: 'high', text: 'Store type mismatch (file is PKCS12 but Java expects JKS)', check: 'keytool -list -keystore file -storetype PKCS12 -storepass <pw>', fix: 'Set -Djavax.net.ssl.trustStoreType=PKCS12 explicitly' },
      { likely: 'high', text: 'Wrong password', check: 'keytool -list -keystore file -storepass <pw>', fix: 'Verify password; regenerate store if lost' },
      { likely: 'medium', text: 'File corrupted or truncated', check: 'file <keystore-file>; ls -la <keystore-file>', fix: 'Re-download from cert manager; verify file size > 0' },
      { likely: 'low', text: 'Java version incompatibility (old JKS on new Java or vice versa)', check: 'java -version; keytool -list -v -keystore file', fix: 'Convert: keytool -importkeystore -srcstoretype JKS -deststoretype PKCS12' },
    ],
    tools: ['keystore', 'compat'],
    helpSection: '17',
    commands: [
      'keytool -list -keystore <file> -storepass <password>',
      'keytool -list -keystore <file> -storetype PKCS12 -storepass <password>',
      'file <keystore-file>',
      'keytool -importkeystore -srckeystore old.jks -srcstoretype JKS -destkeystore new.p12 -deststoretype PKCS12',
    ],
  },
]

const toolLabels: Record<string, string> = {
  remote: 'Remote Check',
  conntest: 'Connection Test',
  decode: 'Decode Cert',
  verify: 'Verify Chain',
  chainexpiry: 'Chain Expiry',
  keymatch: 'Key Match',
  compat: 'Compatibility',
  merger: 'Merge Trusts',
  keystore: 'Build KeyStore',
}

export function TroubleshooterWizard() {
  const [selected, setSelected] = useState<string | null>(null)
  const [step, setStep] = useState<'select' | 'diagnose'>('select')

  const scenario = scenarios.find(s => s.id === selected)

  if (step === 'select' || !scenario) {
    return (
      <div className="space-y-4">
        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <h3 className="font-semibold text-gray-900 mb-2">Certificate Troubleshooter</h3>
          <p className="text-sm text-gray-500 mb-4">What are you experiencing?</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {scenarios.map(s => (
              <button key={s.id} onClick={() => { setSelected(s.id); setStep('diagnose') }}
                className="flex items-start gap-3 p-4 rounded-lg border border-gray-200 hover:border-blue-300 hover:bg-blue-50 transition text-left">
                <span className="text-2xl">{s.icon}</span>
                <div>
                  <p className="text-sm font-medium text-gray-900">{s.label}</p>
                  <p className="text-xs text-gray-500 mt-1 line-clamp-2">{s.meaning}</p>
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <span className="text-2xl">{scenario.icon}</span>
            <h3 className="font-semibold text-gray-900">{scenario.label}</h3>
          </div>
          <button onClick={() => { setSelected(null); setStep('select') }}
            className="text-sm text-blue-600 hover:text-blue-800">← Back</button>
        </div>

        <div className="p-3 bg-blue-50 rounded text-sm text-blue-800 mb-4">
          <strong>What this means:</strong> {scenario.meaning}
        </div>

        {/* Causes ranked by likelihood */}
        <h4 className="text-sm font-semibold text-gray-700 mb-2">Most likely causes (check in order):</h4>
        <div className="space-y-3 mb-6">
          {scenario.causes.map((cause, i) => (
            <div key={i} className={`p-3 rounded border-l-4 ${
              cause.likely === 'high' ? 'border-red-400 bg-red-50' :
              cause.likely === 'medium' ? 'border-amber-400 bg-amber-50' :
              'border-gray-300 bg-gray-50'
            }`}>
              <div className="flex items-center gap-2 mb-1">
                <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${
                  cause.likely === 'high' ? 'bg-red-200 text-red-800' :
                  cause.likely === 'medium' ? 'bg-amber-200 text-amber-800' :
                  'bg-gray-200 text-gray-700'
                }`}>{cause.likely}</span>
                <span className="text-sm font-medium text-gray-900">{cause.text}</span>
              </div>
              <div className="ml-12 space-y-1">
                <p className="text-xs text-gray-600"><strong>Check:</strong> <code className="bg-white px-1 rounded">{cause.check}</code></p>
                <p className="text-xs text-gray-600"><strong>Fix:</strong> {cause.fix}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Commands */}
        <h4 className="text-sm font-semibold text-gray-700 mb-2">Diagnostic commands:</h4>
        <div className="space-y-2 mb-6">
          {scenario.commands.map((cmd, i) => (
            <div key={i} className="flex items-center gap-2">
              <pre className="flex-1 text-xs font-mono bg-gray-900 text-green-400 p-2 rounded overflow-x-auto">{cmd}</pre>
              {!cmd.startsWith('#') && <CopyButton text={cmd} />}
            </div>
          ))}
        </div>

        {/* Related tools */}
        <h4 className="text-sm font-semibold text-gray-700 mb-2">Use these tools:</h4>
        <div className="flex flex-wrap gap-2">
          {scenario.tools.map(tool => (
            <span key={tool} className="px-3 py-1.5 bg-blue-100 text-blue-800 rounded text-xs font-medium">
              {toolLabels[tool] || tool}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}
