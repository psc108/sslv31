#!/usr/bin/env python
import configparser
import os

def get_required_properties():
    return [
        'frontendHostnames',
        'frontendLoadbalancerHostname',
        'backendHostnames',
        'backendLoadbalancerHostname',
        'propertiesEncryptionAlgorithm',
        'propertiesEncryptionKey',
        'serviceAccountPassword',
        'serviceAccountPasswordEncrypted',
        'javaSecurityPassword',
        'javaSecurityPasswordEncoded',

        'dbUrl',
        'dbUserPrefix',
        'dbUserPassword',

        'rabbitmqHosts',
        'rabbitmqPort',
        'rabbitmqUserPassword',
        'rabbitmqVirtualHost',

        'idmHosts',
        'idmPort',
        'idmDomain',
        'idmAdmin',
        'idmAdminPassword'
    ]

def define_properties(config):
    extended_config = {
        'installRoot': '/opt/ecs',
        'installParts': 'backend,frontend,frontend-lb,doc',
        'logRoot': '/var/log/ecs',
        #'hostname': '${hostname}', # hostname should be useless - ignored
        'targetUser': 'ecs',
        'enableManagementSecurity': 'false',
        'loggingPatternFile': '%%d{yyyy-MM-dd HH:mm:ss.SSS} %%5p [%%15.15t] %%-40.40logger{39} [%%8.-8X{logCorrelationId}] : %%msg%%n',
        'loggingPatternConsole': '%%d{yyyy-MM-dd HH:mm:ss.SSS} %%clr(%%5p) [%%15.15t] %%clr(%%-40.40logger{39}){cyan} [%%8.-8X{logCorrelationId}] : %%msg%%n',

        'flywayEnabled': 'true',
        'dbType': 'mysql',
        'propertiesEncryptionKey': '${propertiesEncryptionKey}',
        'propertiesEncryptionAlgorithm': '${propertiesEncryptionAlgorithm}',
        'sslEnabled': 'true',
        'sslPassphrase': '${javaSecurityPassword}',
        'sslPassphraseEncoded': '${javaSecurityPasswordEncoded}', # probably useless - ignored
        'configPassword': '${serviceAccountPassword}',
        'auditLogPassword': '${serviceAccountPassword}',
        'sslCiphers': 'TLS_RSA_WITH_AES_256_GCM_SHA384,TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384,TLS_RSA_WITH_AES_128_CBC_SHA,TLS_RSA_WITH_AES_128_GCM_SHA256,TLS_ECDHE_ECDSA_WITH_3DES_EDE_CBC_SHA,TLS_ECDHE_ECDSA_WITH_AES_128_CBC_SHA,TLS_ECDHE_RSA_WITH_3DES_EDE_CBC_SHA,TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA,TLS_ECDHE_ECDSA_WITH_AES_128_CBC_SHA256,TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256,TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA256,TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256',
        'sslUICiphers': 'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES128-GCM-SHA256:DHE-RSA-AES256-SHA384:HIGH:!aNULL:!eNULL:!EXPORT:!DES:!RC4:!MD5:!PSK:!SRP:!CAMELLIA',
        'ecdhCurve': 'secp384r1',
        'externalLoginSystem': 'none',
        'externalLogout': '',

        'supportedLanguages': 'en-US,nl,zh-CN,fi,hu',
        'includeTestContent': 'false',

        'rabbitmqAddresses': '${rabbitmqAddresses}',
        'rabbitmqSSLEnabled': 'true',
        'rabbitmqVirtualHost': '${rabbitmqVirtualHost}',
        'eventDevelopmentMode': 'false',
        'eventUrlPublic': 'https://${backendLoadbalancerHostname}:443',
        'eventUrlPrivate': 'https://${backendLoadbalancerHostname}:443',
        'diagnosticBackendHosts': '${backendHostnames}',
        'eventPort': '8092',
        'eventRabbitmqUsername': 'event',
        'eventRabbitmqPassword': '${rabbitmqUserPassword}',
        'eventDbUrl': get_db_url(config, '_event'),
        'eventDbUser': '${dbUserPrefix}_event',
        'eventDbPassword': '${dbUserPassword}',
        'eventServiceAccountDomainName': 'system',
        'eventServiceAccountUsername': 'eventSvc',
        'eventServiceAccountPassword': '${serviceAccountPasswordEncrypted}',
        'l3vmOptions': '-Xmx128m',

        'idmHosts': '${idmHosts}',
        'idmPort': '${idmPort}',
        'idmUrlPrivate': '${idmUrlPrivate}',
        'idmUrlAdmin': '${idmUrlPrivate}',
        'securityTrustAllCerts': 'true',

        'blobStoreUrlPrivate': 'https://${backendLoadbalancerHostname}:443',
        'blobStoreUrlPublic': 'https://${backendLoadbalancerHostname}:443',
        'blobStorePort': '8091',
        'blobStoreDbUrl': get_db_url(config, '_blobstore'),
        'blobStoreDbUser': '${dbUserPrefix}_blobstore',
        'blobStoreDbPassword': '${dbUserPassword}',
        'blobStoreRabbitmqUsername': 'blobstore',
        'blobStoreRabbitmqPassword': '${rabbitmqUserPassword}',
        'l2vmOptions': '-Xmx256m',

        'catalogUrlPrivate': 'https://${backendLoadbalancerHostname}:443',
        'catalogUrlPublic': 'https://${backendLoadbalancerHostname}:443',
        'catalogPort': '8093',
        'catalogDbUrl': get_db_url(config, '_catalog'),
        'catalogDbUser': '${dbUserPrefix}_catalog',
        'catalogDbPassword': '${dbUserPassword}',
        'catalogRabbitmqUsername': 'catalog',
        'catalogRabbitmqPassword': '${rabbitmqUserPassword}',
        'catalogServiceAccountDomainName': 'system',
        'catalogServiceAccountUsername': 'catalogSvc',
        'catalogServiceAccountPassword': '${serviceAccountPasswordEncrypted}',
        'proxyOptions': '${proxyOptions}',
        'l1vmOptions': '-Xmx1g',

        'diagnosticFrontendHosts': '${frontendHostnames}',
        'managementUiPort': '8102',
        'managementUiContextPath': '/ui/management',
        'managementUiUrlPublic': 'https://${frontendLoadbalancerHostname}:443',

        'portalUiPort': '8202',
        'portalUiContextPath': '/ui/portal',
        'portalUiUrlPublic': 'https://${frontendLoadbalancerHostname}:443',

        'fulfillmentUrlPrivate': 'https://${backendLoadbalancerHostname}:443',
        'fulfillmentUrlPublic': 'https://${backendLoadbalancerHostname}:443',
        'fulfillmentPort': '8097',
        'fulfillmentDbUrl': get_db_url(config, '_fulfill'),
        'fulfillmentDbUser': '${dbUserPrefix}_fulfill',
        'fulfillmentDbPassword': '${dbUserPassword}',
        'fulfillmentRabbitmqUsername': 'fulfillment',
        'fulfillmentRabbitmqPassword': '${rabbitmqUserPassword}',
        'fulfillmentServiceAccountDomainName': 'system',
        'fulfillmentServiceAccountUsername': 'fulfillmentSvc',
        'fulfillmentServiceAccountPassword': '${serviceAccountPasswordEncrypted}',

        'cleanUpActivityLogHoursLimit': '168',
        'cleanUpActivityLogJobStartHours': '1',
        'cleanUpActivityLogJobIntervalHours': '12',

        'v2wrapperUrlPrivate': '',
        'v2wrapperUrlPublic': '',
        'v2wrapperPort': '',
        'v2wrapperDbUrl': '',
        'v2wrapperDbUser': '',
        'v2wrapperDbPassword': '',
        'v2wrapperRabbitmqUsername': '',
        'v2wrapperRabbitmqPassword': '',
        'v2wrapperServiceAccountDomainName': '',
        'v2wrapperServiceAccountUsername': '',
        'v2wrapperServiceAccountPassword': '',

        'customersUrlPrivate': 'https://${backendLoadbalancerHostname}:443',
        'customersUrlPublic': 'https://${backendLoadbalancerHostname}:443',
        'customersPort': '8090',
        'customersDbUrl': get_db_url(config, '_customers'),
        'customersDbUser': '${dbUserPrefix}_customers',
        'customersDbPassword': '${dbUserPassword}',
        'customersRabbitmqUsername': 'customer',
        'customersRabbitmqPassword': '${rabbitmqUserPassword}',
        'customersServiceAccountDomainName': 'system',
        'customersServiceAccountUsername': 'customersSvc',
        'customersServiceAccountPassword': '${serviceAccountPasswordEncrypted}',
        'customersSecurityAdminProjectName': '${idmAdmin}',
        'customersSecurityAdminDomainName': '${idmDomain}',
        'customersSecurityAdminUsername': '${idmAdmin}',
        'customersSecurityAdminPassword': '${idmAdminPassword}',
        'idmDbEnabled': 'false',
        'idmDbUrl': '',
        'idmDbUser': '',
        'idmDbPassword': '',

        'apiDocHost': get_property_first_hostname(config['frontendHostnames']),
        'apiDocPort': '8098',
        'l4vmOptions': '-Xmx128m',

        'requestUrlPrivate': 'https://${backendLoadbalancerHostname}:443',
        'requestUrlPublic': 'https://${backendLoadbalancerHostname}:443',
        'requestPort': '8096',
        'requestDbUrl': get_db_url(config, '_request'),
        'requestDbUser': '${dbUserPrefix}_request',
        'requestDbPassword': '${dbUserPassword}',
        'requestRabbitmqUsername': 'request',
        'requestRabbitmqPassword': '${rabbitmqUserPassword}',
        'requestServiceAccountDomainName': 'system',
        'requestServiceAccountUsername': 'requestSvc',
        'requestServiceAccountPassword': '${serviceAccountPasswordEncrypted}',

        'serviceInstancesUrlPrivate': 'https://${backendLoadbalancerHostname}:443',
        'serviceInstancesUrlPublic': 'https://${backendLoadbalancerHostname}:443',
        'serviceInstancesPort': '8094',
        'serviceInstancesDbUrl': get_db_url(config, '_svcinst'),
        'serviceInstancesDbUser': '${dbUserPrefix}_svcinst',
        'serviceInstancesDbPassword': '${dbUserPassword}',
        'serviceInstancesRabbitmqUsername': 'svcinst',
        'serviceInstancesRabbitmqPassword': '${rabbitmqUserPassword}',
        'serviceInstancesServiceAccountDomainName': 'system',
        'serviceInstancesServiceAccountUsername': 'serviceInstanceSvc',
        'serviceInstancesServiceAccountPassword': '${serviceAccountPasswordEncrypted}',

        'serviceInstancesCmdbEnabled': 'false',
        'serviceInstancesCmdbAdapterId': '',

        'serviceInstancesSnowAdapterUrl': '',
        'serviceInstancesSnowAdapterUsername': '',
        'serviceInstancesSnowAdapterPassword': '',
        'serviceInstancesSnowAdapterPath': '',

        'serviceInstancesSnowGbpAdapterUrl': '',
        'serviceInstancesSnowGbpAdapterUsername': '',
        'serviceInstancesSnowGbpAdapterPassword': '',
        'serviceInstancesSnowGbpAdapterPath': '',

        'serviceInstancesSmaxAdapterUrl': '',
        'serviceInstancesSmaxAdapterTenantId': '',
        'serviceInstancesSmaxAdapterUserName': '',
        'serviceInstancesSmaxAdapterPassword': '',
        'serviceInstancesUcmdbAdapterUrl': '',

        'pricingUrlPrivate': 'https://${backendLoadbalancerHostname}:443',
        'pricingUrlPublic': 'https://${backendLoadbalancerHostname}:443',
        'pricingPort': '8095',
        'pricingDbUrl': get_db_url(config, '_pricing'),
        'pricingDbUser': '${dbUserPrefix}_pricing',
        'pricingDbPassword': '${dbUserPassword}',
        'pricingRabbitmqUsername': 'pricing',
        'pricingRabbitmqPassword': '${rabbitmqUserPassword}',
        'pricingServiceAccountDomainName': 'system',
        'pricingServiceAccountUsername': 'pricingSvc',
        'pricingServiceAccountPassword': '${serviceAccountPasswordEncrypted}',

        'reportingUrlPrivate': 'https://${backendLoadbalancerHostname}:443',
        'reportingUrlPublic': 'https://${backendLoadbalancerHostname}:443',
        'reportingPort': '8099',
        'reportingDbUrl': get_db_url(config, '_reporting'),
        'reportingDbUser': '${dbUserPrefix}_reporting',
        'reportingDbPassword': '${dbUserPassword}',
        'reportingRabbitmqUsername': 'reporting',
        'reportingRabbitmqPassword': '${rabbitmqUserPassword}',
        'reportingServiceAccountDomainName': 'system',
        'reportingServiceAccountUsername': 'reportingSvc',
        'reportingServiceAccountPassword': '${serviceAccountPasswordEncrypted}',

        'ticketingUrlPrivate': 'https://${backendLoadbalancerHostname}:443',
        'ticketingUrlPublic': 'https://${backendLoadbalancerHostname}:443',
        'ticketingPort': '8101',
        'ticketingDbUrl': get_db_url(config, '_ticketing'),
        'ticketingDbUser': '${dbUserPrefix}_ticketing',
        'ticketingDbPassword': '${dbUserPassword}',
        'ticketingRabbitmqUsername': 'ticketing',
        'ticketingRabbitmqPassword': '${rabbitmqUserPassword}',
        'ticketingServiceAccountDomainName': 'system',
        'ticketingServiceAccountUsername': 'ticketingSvc',
        'ticketingServiceAccountPassword': '${serviceAccountPasswordEncrypted}',

        'ticketingSnowAdapterUrl': '',
        'ticketingSnowAdapterUsername': '',
        'ticketingSnowAdapterPassword': '',
        'ticketingSnowAdapterIncidentUrl': '',
        'ticketingSnowAdapterUrgencyRestQuery': '',
        'ticketingSnowAdapterIncidentUiUrlPattern': '',

        'ticketingSmaxAdapterUrl': '',
        'ticketingSmaxAdapterTenantId': '',
        'ticketingSmaxAdapterUserName': '',
        'ticketingSmaxAdapterPassword': '',
        'ticketingSmaxAdapterRequestUiUrlPattern': '',

        'itopUrl': '',
        'itopUserName': '',
        'itopPassword': '',
        'itopRequestCorrelationIdField': '',
        'itopCiCorrelationIdField': '',

        'configUrlPrivate': 'https://${backendLoadbalancerHostname}:443',
        'configUrlPublic': 'https://${backendLoadbalancerHostname}:443',
        'configDbUrl': get_db_url(config, '_config'),
        'configDbUser': '${dbUserPrefix}_config',
        'configDbPassword': '${dbUserPassword}',
        'configPort': '8103',
        'configRabbitmqUsername': 'config',
        'configRabbitmqPassword': '${rabbitmqUserPassword}',

        'exportUrlPrivate': 'https://${backendLoadbalancerHostname}:443',
        'exportUrlPublic': 'https://${backendLoadbalancerHostname}:443',
        'exportDbUrl': get_db_url(config, '_export'),
        'exportDbUser': '${dbUserPrefix}_export',
        'exportDbPassword': '${dbUserPassword}',
        'exportPort': '8105',
        'exportServiceAccountDomainName': 'system',
        'exportServiceAccountUsername': 'exportSvc',
        'exportServiceAccountPassword': '${serviceAccountPasswordEncrypted}',
        'exportRabbitmqUsername': 'export',
        'exportRabbitmqPassword': '${rabbitmqUserPassword}',

        'externalEventsUrlPrivate': 'https://${backendLoadbalancerHostname}:443',
        'externalEventsUrlPublic': 'https://${backendLoadbalancerHostname}:443',
        'externalEventsDbUrl': get_db_url(config, '_extevt'),
        'externalEventsDbUser': '${dbUserPrefix}_extevt',
        'externalEventsDbPassword': '${dbUserPassword}',
        'externalEventsPort': '8106',
        'externalEventsServiceAccountDomainName': 'system',
        'externalEventsServiceAccountUsername': 'externalEventsSvc',
        'externalEventsServiceAccountPassword': '${serviceAccountPasswordEncrypted}',
        'externalEventsRabbitmqUsername': 'extevt',
        'externalEventsRabbitmqPassword': '${rabbitmqUserPassword}',

        'diagnosticUrlPrivate': 'https://${backendLoadbalancerHostname}:443',
        'diagnosticUrlPublic': 'https://${backendLoadbalancerHostname}:443',
        'diagnosticHost': get_property_first_hostname(config['backendHostnames']),
        'diagnosticPort': '8104',
        'diagnosticServiceAccountDomainName': 'system',
        'diagnosticServiceAccountUsername': 'monitor',
        'diagnosticServiceAccountPassword': '${serviceAccountPasswordEncrypted}',
        'diagnosticNginxDisabled': 'true',
        'diagnosticNginxHosts': 'na',
        'diagnosticIdmHosts': '${idmHosts}',
        'diagnosticIdmPort': '${idmPort}',
        'diagnosticRabbitAdminPort': '${rabbitmqPort}',
        'diagnosticRabbitHosts': '${rabbitmqHosts}',
        'diagnosticRabbitVhostSuffix': '',
        'diagnosticRabbitUser': 'catalog', # some existing user, e.g. 'catalog'
        'diagnosticRabbitPassword': '${rabbitmqUserPassword}',
        'diagnosticEnvironment': 'Dev',
        'diagnosticExportCloudWatch': 'false',
        'diagnosticExportPrometheus': 'true',

        'snowEnabled': 'false',
        'snowUrl': '',
        'snowUser': '',
        'snowPassword': '',

        'snowEventEnabled': 'false',
        'snowEventUrl': '',
        'snowEventUserName': '',
        'snowEventPassword': '',

        'grafanaEnabled': 'false',
        'grafanaUrlPrivate': '',
        'grafanaUser': '',
        'grafanaPassword': ''
    }
    for key in extended_config:
        val = extended_config[key]
        val = replace_in_template(val, config)
        extended_config[key] = val
    return extended_config


def get_db_url(config, db_name_suffix):
    """
    Completes MySQL URL for given SSP service
    """
    db_url_pattern = config['dbUrl']
    db_name_prefix = config['dbUserPrefix']
    return db_url_pattern.replace('[db_name]', db_name_prefix + db_name_suffix)


def read_configuration(source_dir, property_file_name):
    """
    Reads setup.properties and returns properties as a dictionary. Section names are prepended to property name.
    """
    config = {}
    config_path = os.path.join(source_dir, property_file_name)
    config_parser = configparser.ConfigParser(allow_no_value=True)
    config_parser.optionxform = str

    # enhanced_config = StringIO.StringIO()
    # enhanced_config.write('[dummysection]\n')

    with open(config_path, "r") as config_file:
        config_parser.read_file(config_file)
        # enhanced_config.write(config_file.read())
    # config_parser.readfp(enhanced_config)
    for section in config_parser.sections():
        for name, value in config_parser.items(section):
            config[name] = value
    # print('Config: {}'.format(config))
    return config


def check_configuration(config):
    """
    Check all required_properties
    """
    missing_keys = []
    required_properties = get_required_properties()
    for key in required_properties:
        try:
            val = config[key]
            if not val:
                missing_keys.append(key)
        except KeyError:
            missing_keys.append(key)
    if len(missing_keys) != 0:
        raise ValueError('Required parameters are not specified: ' + str(missing_keys))

    config['rabbitmqAddresses'] = get_property_rabbitmq_addresses(config['rabbitmqHosts'], config['rabbitmqPort'])
    config['idmUrlPrivate'] = get_property_idm_url_private(config['idmHosts'], config['idmPort'], '/api/idm')

    return config


def get_property_rabbitmq_addresses(rabbitmq_hosts, rabbitmq_port):
    hosts = rabbitmq_hosts.split(',')
    new_hosts = []
    for host in hosts:
        new_hosts.append('{}:{}'.format(host.strip(), rabbitmq_port))
    return ','.join(new_hosts)


def get_property_idm_url_private(idm_hosts, idm_port, url_context):
    host = idm_hosts.split(',')[0].strip()
    return 'https://{}:{}{}'.format(host, idm_port, url_context)

def get_property_first_hostname(hosts):
    return  hosts.split(',')[0].strip()

def read_template(source_dir, property_file_name):
    """
    Reads setup.properties.template and returns content as a string.
    """
    template_path = os.path.join(source_dir, property_file_name)
    template = ''
    with open(template_path, "r") as template_file:
        template = template_file.read()
    # print('Template: {}'.format(template))
    return template


def write_file(content, source_dir, property_file_name):
    """
    Writes setup.properties.
    """
    property_file_path = os.path.join(source_dir, property_file_name)
    with open(property_file_path, "w") as property_file:
        property_file.write(content)


def replace_in_template(template, config):
    """
    Replaces all occurrences of properties from config (dictionary) in template (string) and returns replaced content.
    """
    content = template
    for key in config:
        val = config[key]
        # print('Replacing: {} -> {}'.format('${'+key+'}', val))
        content = content.replace('${' + key + '}', val)
    # print('Result: {}'.format(content))
    return content


if __name__ == "__main__":
    source_dir = '.'
    template_string = read_template(source_dir, 'setup.properties.template')
    quick_setup_config = read_configuration(source_dir, 'quickSetup.properties')
    quick_setup_config = check_configuration(quick_setup_config)
    extended_config = define_properties(quick_setup_config)
    result = replace_in_template(template_string, extended_config)
    write_file(result, source_dir, 'setup.properties')
