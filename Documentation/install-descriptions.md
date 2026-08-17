On Premise Installation Guide
This guide describes on premise installation of CPS Shared Services Portal (SSP). 
Deployment Overview
Requirements
VMs
DB
Deployment Topology
Single-node deployment
HA deployment
Installation
Common steps
Step 1: Installation account
Step 2: Check system updates
Step 3: Get scripts
1. Administration node
Step 1: Install Java
Step 2: Install python
Step 3: Edit installation property file
Step 4: Prepare SSL certificates
2. RabbitMQ
Step 1: Configure PackageCloud repository
Step 2: Install packages
Step 3: Start RabbitMQ Server
Step 4: Configure RabbitMQ Server
Step 5: Enable Management UI
Step 6: Enable SSL
Step 7: Create RabbitMQ users and vhost
Step 8: Check configuration
RabbitMQ Troubleshooting
3. KeyStone
Step 1: Create datatabase for KeyStone
Step 2: Install KeyStone
Step 3. Enable SSL and configure URL path
Step 4. Finalize installation
Step 5: Install SSP extension
Step 6: Import data
Step 7: Check KeyStone data
Keystone Troubleshooting
4. SSP backend and frontend
Step 1: Install Java
Step 2: Install python
Step 3: Install Node.js
Step 4: Install nginx
Step 5: Download Shared Services binaries
Step 6: Pick up setup.properties file
Step 7: Create MySQL databases and users
Step 8: SSL
Step 9: Install Shared Services
Step 10: Check SSP installed
HA Installation
RabbitMQ - HA
Step 1: Hostname resolution
Step 2: Install nodes
Step 3: Check RabbitMQ node names
Step 4: Open ports
Step 5: Configure common Erlang cookie
Step 6: Add node2 to cluster
Step 7: Check cluster
Appendix 1: SSL
Step 1: Generate CA private key and certificate
Step 2: Install java
Step 3: Generate server private key and certificate
Step 4: Create Java Keystore and Truststore
Step 5: Copy files to target node
Appendix 2: Password encryption
Step 1: Install Jasypt and BouncyCastle
Step 2: Encrypt a password
Appendix 3: Shared Service upgrade and re-installation
Complete replacement
Partial replacement
Deployment Overview
The SSP system consist of Frontend and Backend SSP services, RabbitMQ (messaging service), OpenStack Keystone (identity management - IdM 
service) and MySQL database on the same (private) network. More complex deployments involves also loadbalancers/proxy severs. MySQL database is 
typically provided by a cloud provider or by a dedicated team inside your company, so it is usually not needed to install and manage it on your own. 
RabbitMQ and KeyStone are not expected to be provided, so this guide will describe the installation shortly. Frontend and Backend SSP Services 
installation is the primary target of this topic. This guide also assumes an administration VM with a visibility to SSP system component VMs, so that an 
administrator can manage all the components from the administration VM.
Requirements
VMs
Each SSP system component is usually installed on a standalone VM. Recommended VM parameters differ according to component type and deployment 
purpose (e.g. staging/testing vs. production environment).
Component
Frontend node
Backend node
RabbitMQ node
KeyStone node
MySQL node
CPU (staging/production)
4/8
8/16
4/4
2/4
Memory GB (staging/production)
8/16
16/32
4/8
4/4
8/16
Administration node 2/2
16
4/4
Disk Space
50 GB
50 GB
20 GB
20 GB
250 GB
20 GB
Note that these capacity recommendations are provided as a best quess and can vary on your deployment - it depends on the SSP System load.
DB
MySQL server version 8.0.25 (or higher) is supported including Amazon RDS (MySQL).
MariaDB is not supported.
Deployment Topology
Deployment topology can vary depending on deployment purpose. For the purpose of this guide let's assume 2 model cases:
Single-node deployment: A deployment with standalone (single) VM for each of SSP System component. This deployment suits well for 
development/testing/staging environment(s).
HA deployment: A deployment with 2 (or more) VMs for each of SSP System component. VMs for the same component type should be placed in 
different Availability Zones. The HA deployment type suits well for production environment.
Single-node deployment
A single-node deployment contains a standalone single VM for each of SSP System component type. 
Rounded-corner rectangles mean VMs, Sharp-corner rectangles mean services (or groups of services) on a VM. All SSP System VMs communicate to 
each other on the same private network, relevant opened ports are depicted. Only nginx service on "Frontend services" VM provides 443 port to a public 
network. 
The picture shows standalone VMs for
Frontend services: The Admin UI is internally accessible on port 8102. The Portal UI is accessible on port 8202. nginx server works as a proxy 
that is accessible on standard https port 443 for public connections. Ports 8102 and 8202 are open by installation, but can be hidden behind 
firewall.
Backend services: Each backend service is internally accessible on one of ports 8090-8106. Access from local network is mediated by standard 
https port 443 of nginx server. (The nginx server on backend services VM is optional.)
RabbitMQ: Standalone node for RabbitMQ accepts connections on local network on ports 5671 (and 15671 for UI management).
MySQL: Standalone node for MySQL database accepts connection on local network on port 3306.
KeyStone: Standalone node for OpenStack KeyStone server that accepts connection on local network on port 5000.
On the left side, there is an Administration node for management purposes that can connect to all SSP deployment nodes using ssh (connections 
and standard ssh port 22 are not depicted on each node for simplicity).
SSP System manages external fulfillment systems (e.g. AWS, Azure, GCP, vRA, Ansible Tower, Microfocus OO, etc.). External fulfillment systems desired 
for your solution must be accessible for SSP Fulfillment service.
HA deployment
HA deployment contains 2 (or more) VMs for each of SSP System components. VMs for the same component type should be placed in different 
Availability Zones (AZ). There should be established an inter AZ synchronization. It is up to a reliable Load Balancer to track availability of services and 
redirect trafic to other AZ if needed.
The HA deployment type suits well for production environment.
The HA deployment picture shows 2 availability zones and inter AZ synchronization. Communication between frontend and backend services and 
KeyStone is mediated by LoadBalancer. Backend services know both RabbitMQ nodes and Load Ballancer is not involved in messaging.
Installation
Before installation, plan carrefully the deployment type, networks and databases to be used. Create well sized VMs - see the previous chapter for 
inspiration. All the servers (irrespective of the SSP component to be installed to the server) should have a non-root user with sudo privileges to do the 
installation on behalf of, up-to-date OS and unpacked scripts comming along with this guide - see 
Common Steps
In general, you can install SSP components in following order:
1.  
2.  
3.  
4.  
Administration node
RabbitMQ 
KeyStone
Backend and Frontend services
Common steps
Each node (
irrespective of kind of SSP system component to be installed
 for details. 
) should comform to prerequesities mentioned in this chapter.
Step 1: Installation account
The installation process uses a non-root user to run commands described further. The account must have an ability to run 
sudo
 command. For frontend 
and backend nodes, the user must be named 'ecs'. On other nodes, the user can be named differently, but this installation guide supposes the 'ecs' 
account on all the nodes for simplicity.
If no such account exists, create the account in this way (as root):
[root@localhost ~]# useradd ecs
[root@localhost ~]# passwd ecs
Enter and retype a password. Then enable the user to run 
command:
sudo
 command without specifying password: Backup 
/etc/sudoers
 file and run  
visudo
[root@localhost ~]# cp /etc/sudoers{,.backup_$(date +%Y%m%d)}
[root@localhost ~]# visudo
Command 
visudo
as vi editor).
 opens 
/etc/sudoers
. Scroll down to the bottom of the file, append following line and save changes (visudo is used in the same way 
ecs  ALL=(ALL) NOPASSWD:ALL
Step 2: Check system updates
Further commands assume to be run under non-root user (e.g. ecs).
To check for any updates available type
dnf check-update
To upgrade all of your system software type
sudo dnf update
Step 3: Get scripts
This guide refers to scripts that can automate some parts of installation. Download 
manual-installation-scripts.tar.gz
 (the name can differ 
according to the version of scripts). The archived scripts can be useful on all nodes, especially on the Administration node, frontend/backend node(s), but 
also on RabbitMQ, KeyStone and MySQL nodes.  
To upload the archive from you Windows machine to a (Linux) node, you can use pscp command below. (pscp is part of 
placeholder with host ip.
) 
PuTTY. Replace <host_ip> 
pscp manual-installation-scripts.tar.gz ecs@<host_ip>:/home/ecs
On the target node: Unpack scripts to 
/opt/scripts
 directory (you can use different directory, but later chapters will refer to /opt/scripts)
sudo mkdir /opt/scripts
sudo tar -xf manual-installation-1.5.0-SNAPSHOT-scripts.tar.gz -C /opt/scripts
1. Administration node
The administration node is the place for preparing configuration files, encrypting passwords within configuration files, generating SSL keys/certificates (if 
applicable), etc. The configuration and SSL files will be distributed to other nodes on demand.
Step 1: Install Java
sudo dnf install java-11-openjdk -y
After installation, check java is installed correctly:
java -version
Step 2: Install python
Run command:
sudo dnf install python2 python2-pyyaml -y
Step 3: Edit installation property file
 contains the most importat properties that rule the installation. It is needed to setup the 
The file 
/opt/scripts/ssp/quickSetup.properties
properties carefully - especially hostnames/URLs, users and credentials to for RabbitMQ, Keystone, MySQL and frontend and backend services. 
Passwords in the file can be specified in plain text, but it is recommended to encrypt them - see 
Password encryption
Edit installation properties, for example:
 chapter.
sudo vi /opt/scripts/ssp/quickSetup.properties
Once editted, run buildProperties.py python script to generate full setup.properties finally used for installation:
cd /opt/scripts/ssp
sudo python2 buildProperties.py
We will copy prepared setup.properties file to backend/frontend nodes later.
Step 4: Prepare SSL certificates
All HTTP interfaces of all SSP system nodes (Backend/Frontend Services node(s), RabbitMQ node and KeyStone node) should be secured by SSL. 
(Securing database connection is behind the scope of this guide.)
SSL enablement on a node/server needs in general at least 3 files: SSL private key, server certificate (with public key) and a certificate of Certificate 
Authority that signed the server certificate. The recommended way to obtain these files is to ask an administrator, because your company has probably a 
way how to generate key/certificate for a new server and how to distribute CA certificates (if the CA certificate is not publicly trusted).
If you decided to generate SSL files by yourself see 
SSL
 chapter for details. If you obtain a private key and certificates for a server from administrator, you 
still need to prepare java security keystore and truststore files for frontend and backend nodes - see 
and Truststore") for details.
SSL
 chapter (especially step "Create Java Keystore 
Note that you need to prepare SSL files for all SSP component nodes - Frontend, Backend, RabbitMQ and KeyStone nodes.
2. RabbitMQ
Install RabbitMQ according to the RabbitMQ documentation for your OS. Following examples are tested on CentOS Stream 8 and can differ in details with 
your case.
Step 1: Configure PackageCloud repository
Copy whole content of the window to the command line at once:
sudo tee -a /etc/yum.repos.d/rabbitmq.repo << EOF
# In /etc/yum.repos.d/rabbitmq.repo
##
## Zero dependency Erlang
##
[rabbitmq_erlang]
name=rabbitmq_erlang
baseurl=https://packagecloud.io/rabbitmq/erlang/el/8/\$basearch
repo_gpgcheck=1
gpgcheck=1
enabled=1
# PackageCloud's repository key and RabbitMQ package signing key
gpgkey=https://packagecloud.io/rabbitmq/erlang/gpgkey
       https://github.com/rabbitmq/signing-keys/releases/download/2.0/rabbitmq-release-signing-key.asc
sslverify=1
sslcacert=/etc/pki/tls/certs/ca-bundle.crt
metadata_expire=300
[rabbitmq_erlang-source]
name=rabbitmq_erlang-source
baseurl=https://packagecloud.io/rabbitmq/erlang/el/8/SRPMS
repo_gpgcheck=1
gpgcheck=0
enabled=1
# PackageCloud's repository key and RabbitMQ package signing key
gpgkey=https://packagecloud.io/rabbitmq/erlang/gpgkey
       https://github.com/rabbitmq/signing-keys/releases/download/2.0/rabbitmq-release-signing-key.asc
sslverify=1
sslcacert=/etc/pki/tls/certs/ca-bundle.crt
metadata_expire=300
##
## RabbitMQ server
##
[rabbitmq_server]
name=rabbitmq_server
baseurl=https://packagecloud.io/rabbitmq/rabbitmq-server/el/8/\$basearch
repo_gpgcheck=1
gpgcheck=0
enabled=1
# PackageCloud's repository key and RabbitMQ package signing key
gpgkey=https://packagecloud.io/rabbitmq/rabbitmq-server/gpgkey
       https://github.com/rabbitmq/signing-keys/releases/download/2.0/rabbitmq-release-signing-key.asc
sslverify=1
sslcacert=/etc/pki/tls/certs/ca-bundle.crt
metadata_expire=300
[rabbitmq_server-source]
name=rabbitmq_server-source
baseurl=https://packagecloud.io/rabbitmq/rabbitmq-server/el/8/SRPMS
repo_gpgcheck=1
gpgcheck=0
enabled=1
gpgkey=https://packagecloud.io/rabbitmq/rabbitmq-server/gpgkey
sslverify=1
sslcacert=/etc/pki/tls/certs/ca-bundle.crt
metadata_expire=300
EOF
Step 2: Install packages
sudo dnf update -y
sudo dnf -q makecache -y --disablerepo='*' --enablerepo='rabbitmq_erlang' --enablerepo='rabbitmq_server'
Install dependencies from the standard repositories:
sudo dnf install socat logrotate -y
Install modern Erlang and RabbitMQ:
sudo dnf install --repo rabbitmq_erlang --repo rabbitmq_server erlang rabbitmq-server -y
Step 3: Start RabbitMQ Server
Enable automatic RabbitMQ server start after reboot:
sudo chkconfig rabbitmq-server on
Start RabbitMQ server:
sudo service rabbitmq-server start
Step 4: Configure RabbitMQ Server
Create administrator's account, . replace <password> placeholder with a real password
sudo rabbitmqctl add_user admin <password>
sudo rabbitmqctl set_user_tags admin administrator
Step 5: Enable Management UI
See  for details. https://www.rabbitmq.com/management.html
sudo rabbitmq-plugins enable rabbitmq_management
Node restart is not required after plugin activation.
(optional) Check that server is running:
curl http://localhost:15672
Step 6: Enable SSL
Ask an administrator for
SSL private key for the RabbitMQ server with or without protection by password (and copy it to /etc/rabbitmq/server.key)
the password the private key is protected with (if protected by a password)
SSL certificate for the RabbitMQ server (and copy it to /etc/rabbitmq/server.crt)
SSL certificate of Certification Authority (and copy it to /etc/rabbitmq/ca.crt)
... or generate these files yourself - see  chapter for details. Copy generated files from the administration node to the RabbitMQ node and than to /etc SSL
/rabbitmq as well:
## After SSL certificate generation, files should be in the home directory of ecs user
cd
sudo mv server.key server.crt ca.crt /etc/rabbitmq
Change owner and group to rabbitmq user (otherwise RabbitMQ server will fail to start).
sudo chown rabbitmq:rabbitmq /etc/rabbitmq/server.key /etc/rabbitmq/server.crt /etc/rabbitmq/ca.crt
Create RabbitMQ configuration file. Replace <key_password> placeholder with SSL private key password or remove the lines with password option, if the 
key is not protected by any password.
sudo tee -a /etc/rabbitmq/rabbitmq.conf << EOF
listeners.ssl.default = 5671
ssl_options.cacertfile = /etc/rabbitmq/ca.crt
ssl_options.certfile   = /etc/rabbitmq/server.crt
ssl_options.keyfile    = /etc/rabbitmq/server.key
ssl_options.password   = <key_password>
management.ssl.port       = 15671
management.ssl.cacertfile = /etc/rabbitmq/ca.crt
management.ssl.certfile   = /etc/rabbitmq/server.crt
management.ssl.keyfile    = /etc/rabbitmq/server.key
management.ssl.password   = <key_password>
heartbeat = 580
log.file.level = info
EOF
Restart RabbitMQ server
sudo service rabbitmq-server restart
Open firewall port for outside connections:
sudo firewall-cmd --zone=public --add-port=5671/tcp --permanent
sudo firewall-cmd --zone=public --add-port=15671/tcp --permanent
sudo firewall-cmd --reload
To check web UI is working, try to open address https://<rabbit_host>:15671 in your browser from your local system and use the created admin user 
(above) to authenticate. Note that browser will complain regarding unknown CA until you import the CA cert.
Step 7: Create RabbitMQ users and vhost
Create RabbitMQ users, . replace <password> placeholder with a real password
cd /opt/scripts/rabbit
sudo ./create_users.sh <password>
Create RabbitMQ vHost, optionally replace  for a real vhost name. (If you plan to run multiple independent SSP instances with single shared /ssp
RabbitMQ server, it is needed to run create_vhost.sh script for each SSP instance with unique `vhost` name.)
sudo ./create_vhost.sh /ssp
Step 8: Check configuration
Open address https://<rabbit_host>:15671 in your browser, log in as admin and click on "Admin" tab. You should see following list of users that can access 
virtual host "/ssp":
RabbitMQ Troubleshooting
1) Check status:
sudo rabbitmqctl status
2) Check log file (log file location can be found in the status output):
less /var/log/rabbitmq/rabbit@ssprabbit.log
3) Check permissions in "/ssp" virtual host:
sudo rabbitmqctl list_permissions --vhost /ssp
Sample output
Listing permissions for vhost "/ssp" ...
user    configure       write   read
blobstore       .*      .*      .*
request .*      .*      .*
fulfillment     .*      .*      .*
export  .*      .*      .*
event   .*      .*      .*
catalog .*      .*      .*
ticketing       .*      .*      .*
svcinst .*      .*      .*
customer        .*      .*      .*
pricing .*      .*      .*
config  .*      .*      .*
reporting       .*      .*      .*
4) Check authentication ( ): replace <password> placeholder with a real password
sudo rabbitmqctl authenticate_user admin <password>
sudo rabbitmqctl authenticate_user blobstore <password>
sudo rabbitmqctl authenticate_user catalog <password>
sudo rabbitmqctl authenticate_user config <password>
sudo rabbitmqctl authenticate_user customer <password>
sudo rabbitmqctl authenticate_user event <password>
sudo rabbitmqctl authenticate_user export <password>
sudo rabbitmqctl authenticate_user fulfillment <password>
sudo rabbitmqctl authenticate_user pricing <password>
sudo rabbitmqctl authenticate_user reporting <password>
sudo rabbitmqctl authenticate_user request <password>
sudo rabbitmqctl authenticate_user svcinst <password>
sudo rabbitmqctl authenticate_user ticketing <password>
5) Check complete support info (a bit verbose):
sudo rabbitmqctl report
3. KeyStone
Install OpenStack KeyStone according to the documentation for your OS. Following examples are tested on CentOS Stream 8 and can differ in details with 
your case.
Note: SSP system needs an extension to KeyStone, the compatibility is tested on KeyStone version "Train" and "Xena". Do not use other versions.
Step 1: Create datatabase for KeyStone
Connect to MySQL database server e.g. using command line mysql tool or MySQL Workbench and create database for keystone. Replace <db>, <user> 
and <password> placeholders.
CREATE DATABASE <db>;
CREATE USER <user> IDENTIFIED BY '<password>';
GRANT ALL PRIVILEGES ON <db>.* TO <user>;
Step 2: Install KeyStone
Go through following commands, see  for details. Note, that the latest tested https://docs.openstack.org/install-guide/environment-packages-rdo.html
OpenStack version for SSP is "Xena".
sudo dnf install centos-release-openstack-xena -y
sudo dnf upgrade -y
sudo dnf install python3-openstackclient openstack-selinux -y
Install KeyStone, you can see 
https://docs.openstack.org/keystone/latest/install/keystone-install-rdo.html
 for details.
sudo dnf install openstack-keystone httpd mod_ssl python3-mod_wsgi -y
Edit /etc/keystone/keystone.conf: Configure database connection and enable provider. Replace <db>, <user> and <password> placeholders used above, 
replace <mysql_host> with address of MySQL server.
[database]
connection = mysql+pymysql://<user>:<password>@<mysql_host>/<db>
...
[token]
...
provider = fernet
Populate the Identity service database
sudo su -s /bin/sh -c "keystone-manage db_sync" keystone
Initialize Fernet key repositories
sudo keystone-manage fernet_setup --keystone-user keystone --keystone-group keystone
sudo keystone-manage credential_setup --keystone-user keystone --keystone-group keystone
Configure Apache HTTP server. Edit the
suitable value.
...
ServerName <keystone_ip>
...
/etc/httpd/conf/httpd.conf  
Create a link to the /usr/share/keystone/wsgi-keystone.conf file.
file and configure the
sudo ln -s /usr/share/keystone/wsgi-keystone.conf /etc/httpd/conf.d/
Step 3. Enable SSL and configure URL path
Ask an administrator for
... or generate these files yourself - see 
SSL private key for the KeyStone server (and copy it to /etc/keystone/server.key)
the password the private key is protected with (if protected by a password)
SSL certificate for the KeyStone server (and copy it to /etc/keystone/server.crt)
SSL certificate of Certification Authority (and copy it to /etc/keystone/ca.crt)
SSL
ServerName 
 chapter for details and copy them to /etc/keystone as well:
option. 
## After SSL certificate generation, files should be in the home directory of ecs user
cd
sudo cp server.key server.crt ca.crt /etc/keystone
Change owner and group to keystone.
Replace<keystone_ip> for a 
sudo chown keystone:keystone /etc/keystone/server.key /etc/keystone/server.crt /etc/keystone/ca.crt
If the private key is protected by a password, create a script that will provide the password to the KeyStone. 
Replace <key_password> placeholder
.
sudo tee -a /etc/keystone/server.key.password.sh << EOF
#!/bin/sh
echo "<key_password>"
EOF
Set owner and access to the server.key.password.sh:
sudo chmod 700 /etc/keystone/server.key.password.sh
sudo chown keystone:keystone /etc/keystone/server.key.password.sh
Edit KeyStone configuration file /etc/httpd/conf.d/wsgi-keystone.conf:
change URL path from  to 
/ /api/idm
add following SSLXXX options into VirtualHost section and the password providing script path (if applicable)
<VirtualHost *:5000>
    ...
    WSGIScriptAlias /api/idm /usr/bin/keystone-wsgi-public
    ...
    SSLEngine on
    SSLCertificateFile      /etc/keystone/server.crt
    SSLCertificateKeyFile   /etc/keystone/server.key
    SSLCACertificateFile    /etc/keystone/ca.crt    
    ...
</VirtualHost>
SSLPassPhraseDialog     exec:/etc/keystone/server.key.password.sh
...
Bootstrap the Identity service. Replace <admin_pass> and <keystone_ip> for suitable values.
sudo keystone-manage bootstrap --bootstrap-password <admin_pass> --bootstrap-admin-url https://<keystone_ip>:
5000/api/idm/v3/ --bootstrap-internal-url https://<keystone_ip>:5000/api/idm/v3/ --bootstrap-public-url 
https://<keystone_ip>:5000/api/idm/v3/ --bootstrap-region-id RegionOne
Step 4. Finalize installation
Enable Apache HTTP service to access ca.crt:
sudo setsebool -P httpd_read_user_content 1
sudo systemctl enable httpd.service
sudo systemctl start httpd.service
Open firewall:
Start the Apache HTTP service and configure it to start when the system boots.
sudo firewall-cmd --zone=public --add-port=5000/tcp --permanent
sudo firewall-cmd --reload
Configure the administrative account by setting the proper environmental variables. Replace <admin_pass> and <keystone_ip> for suitable values.
cd
tee -a env.sh << EOF
export OS_USERNAME=admin
export OS_PASSWORD=<admin_pass>
export OS_PROJECT_NAME=admin
export OS_USER_DOMAIN_NAME=Default
export OS_PROJECT_DOMAIN_NAME=Default
export OS_AUTH_URL=https://<keystone_ip>:5000/api/idm/v3
export OS_IDENTITY_API_VERSION=3 
export OS_CACERT=/home/ecs/ca.crt
export no_proxy=<keystone_ip>
EOF
Source env.sh:
chmod u+x env.sh
source env.sh
Test connectivity
openstack domain list
Expected result is following:
Domain list
+----------------------------------+---------+---------+-------------------------------------------------------+
| ID                               | Name    | Enabled | Description                                           |
+----------------------------------+---------+---------+-------------------------------------------------------+
| default                          | Default | True    | The default domain                                    |
+----------------------------------+---------+---------+-------------------------------------------------------+
Step 5: Install SSP extension
Patch render_token.py from the script archive:
sudo cp /opt/scripts/idm/patch/render_token.py /usr/lib/python3.6/site-packages/keystone/common/render_token.py
sudo rm /usr/lib/python3.6/site-packages/keystone/common/__pycache__/render_token.*
Patch policy.json file from the script archive:
sudo cp /opt/scripts/idm/policy.json /etc/keystone/policy.json
Step 6: Import data
Create roles and system domain:
cd /opt/scripts/idm
sudo chown ecs *.sh
./create_roles.sh
System domain users have password "changeit" by default. If you want to use different password, edit PASSWORD property in create_system_domain.sh 
script before running the script.
(Note that the password must be also specified in serviceAccountPassword, serviceAccountPasswordEncrypted and idmAdminPassword properties in 
) quickSetup.properties
./create_system_domain.sh
Step 7: Check KeyStone data
Check created roles:
cd
source env.sh
openstack role list --sort-column Name
The role list should contain many created roles, e.g.
Created roles
+----------------------------------+----------------------------------------+
| ID                               | Name                                   |
+----------------------------------+----------------------------------------+
| 152c8839c02d45319f9dc5c9f335f769 | ACL_ADMIN                              |
| 43bd886434854bce98e342f85e5a1ce1 | BLOB_STORE_ADMIN                       |
| e0ecb65a388b4373b4fbb1ba1253cc9b | BLOB_STORE_CUSTOMER_ORG_ADMIN          |
| d857d07c48a342849933d1db630ca140 | BLOB_STORE_ORG_ADMIN                   |
| 8058e718dadb4bd2b82306a492d4d2bb | BLOB_STORE_USER                        |
| 83d60eb592994e7686d1166b41ab016d | BUSINESS_ACL_ADMIN                     |
| 9400a841ab6546808a6a3be7e496e5ce | BUSINESS_ADAPTER_ADMIN                 |
| 0e33797cbc454be1a9a3e8049c5598a0 | BUSINESS_ADMIN                         |
| 25800cc237f143deb92ed46bd9e8e19d | BUSINESS_ADM_ACCOUNTS_CUSTOMERS_ADMIN  |
| bd93eb5e1f234a389baf942b1197fcbf | BUSINESS_CATALOG_ADMIN                 |
| 86919623e2c54c38a99cf48269536caf | BUSINESS_CUSTOMER_ADMIN                |
| ca684b9c00644bbc9641b0ca247cf3a4 | BUSINESS_CUSTOMER_END_USER             |
| d233aae7ad51459d9ca9f4a07316514f | BUSINESS_CUSTOMER_ORG_ADMIN            |
| cc662887e89e4e90a4d4e671725f36a6 | BUSINESS_DEPARTMENT_ADMIN              |
| b86b624e9e4c43349d0f933b451a9250 | BUSINESS_DEPARTMENT_USER               |
| d7214a26ca3a4a05a34c413c2982a1ee | BUSINESS_OPERATIONS_ADMIN              |
| bde468468795453ca5bdb568ecd41a56 | BUSINESS_ORG_ADMIN                     |
| 577da059123340059af08daecb6d7105 | BUSINESS_PRICING_ADMIN                 |
| a36e4f88102148b6a1b387c9c6df2c04 | BUSINESS_SYSTEM_ADMIN                  |
| 730efdb3fe1a4737a0a7d0def3479c72 | CATALOG_ADMIN                          |
| ef5fe5da1a6640fc881208c41c1ac74b | CATALOG_ADMIN_READER                   |
| 293475220fa74947acfc0404a55f79a4 | CATALOG_CONSUMER                       |
| ba8d6e01362e445aa2dfa231ebb9496a | CATALOG_CUSTOMER_ADMIN                 |
| e382235d63474dbd9dda355b2a718ebb | CATALOG_CUSTOMER_ORG_ADMIN             |
| 2fbd178f3f0745b095394dfa39a270e6 | CATALOG_ORG_ADMIN                      |
| 0cc81b35ec1942f899f2f3622095d186 | CATALOG_PRICING_ADMIN                  |
| e07ee1302d944ab2bd01c5035ae81712 | CATALOG_USER                           |
| 832c1e47f625432b935300f82487e149 | CONFIG_ADAPTER_ADMIN                   |
| 2b6f641f88574332b188dcef80248bad | CONFIG_ADMIN                           |
| a6a5842eae4042a6a8f23b1c8956695b | CONFIG_ADMIN_READER                    |
| e32ada9c1ddf450898c3083769609c70 | CONFIG_CUSTOMER_ADMIN                  |
| be4147df2c2c4cfe9754ebce9bad31d0 | CONFIG_USER                            |
| 400a12c147cf4f87878453b4975fe05b | CPS_SUPPORT                            |
| e91a8a3574e540c0bba6d7dbe91ffafe | CUSTOMERS_ADMIN                        |
| 61edb9d3acfe4ce7b4b53d13b98e95cf | CUSTOMERS_ADMIN_READER                 |
| f103eff6014c49fc968b5a4ed8d72ebe | CUSTOMERS_ADM_ACCOUNTS_CUSTOMERS_ADMIN |
| ac7e00e845314e78a4d972d5b1e9583b | CUSTOMERS_CUSTOMER_ORG_ADMIN           |
| 7d75f43c856941bcae1eb6268c6fd5a9 | CUSTOMERS_ORG_ADMIN                    |
| abe5db47344644e8bbb6233e62c100f8 | CUSTOMERS_SYSTEM_ADMIN                 |
| 9756673c68e24aedbcec820ccb836ff7 | CUSTOMERS_USER                         |
| 6cfbd976c26e4561aa234fde5c105d34 | DIAGNOSTIC_ADMIN                       |
| 0d9e993eb7b946aa93e370e3ab061047 | EVENT_ADMIN                            |
| 20f2702ee77543c0b92ba2f73d702d91 | EXPORT_IMPORT_USER                     |
| 3aba049e9ecf4616a6df244123820263 | FULFILLMENT_ADAPTER_ADMIN              |
| 6a82a2cb6ad7441bbea8ea1af9d8898c | FULFILLMENT_ADMIN                      |
| 6c7ba1497a4e47649abd3c3e3f2d41be | FULFILLMENT_ADMIN_READER               |
| d8d1d7e827b2420d85ff90112820b55f | FULFILLMENT_CUSTOMER_ADMIN             |
| 3113d653c4fc4d60be32ec0401777b74 | FULFILLMENT_CUSTOMER_ORG_ADMIN         |
| 1037e0dc6c864dd18a9fa2aa24345f26 | FULFILLMENT_DESIGN_ADMIN               |
| 00db6dc1785a447cbb90ae2794998863 | FULFILLMENT_NOTIFIER                   |
| a7778d377adc4f4997350cb03cee22ca | FULFILLMENT_OPERATIONS_ADMIN           |
| 9b9593c800454c508c0dc3be23159837 | FULFILLMENT_ORG_ADMIN                  |
| 4a4532b36a994ef8b39191edf9b76c13 | FULFILLMENT_PRICING_ADMIN              |
| e55fe42df82c4db0b09f13e976acddc3 | FULFILLMENT_USER                       |
| 6df93effa21541a08416295f62a2ffb0 | IMPERSONATOR                           |
| 9c2d6b9af89143e6ae7e10915c572a57 | MONITOR                                |
| b5dadac39b4c4580a9f7ad252ac587da | PRICING_ADMIN                          |
| 5e0d2ec2a1ea42919dc3c5226b91d8f3 | PRICING_ADMIN_READER                   |
| 9a21cab937cf47dc9a9a11a316b4db79 | PRICING_CUSTOMER_ORG_ADMIN             |
| ee0f22680e4d48598ade2d77f357db9f | PRICING_HISTORY_ADMIN                  |
| 7f8df11ef7764252b0645489b28b1a2b | PRICING_ORG_ADMIN                      |
| 7a1bd00595e44aceb60152eb53c5e022 | PRICING_USER                           |
| 807a568d66d1474aaffa559de18d5fe5 | REPORTING_ADMIN                        |
| 421e848ab5a44df0863e606084b43c66 | REPORTING_ORG_ADMIN                    |
| dd0f7cd888bc4e0b884dc4fc99318713 | REQUEST_ADMIN                          |
| 9f9226c98d434130b3b797347ff8b351 | REQUEST_ADMIN_READER                   |
| 52803a93b73d4d22875ae4cf20e0485b | REQUEST_CONSUMER                       |
| 438ff699695f430da48cd5f07b7dc0cd | REQUEST_CUSTOMER_ORG_ADMIN             |
| 919c190c36de48d199517e988dd85cb1 | REQUEST_DEPARTMENT_ADMIN               |
| b9eaae832c1b4a488bd124f74cdea9c3 | REQUEST_DEPARTMENT_USER                |
| 57f8d86fc7e54a3db6c351c182d2aaef | REQUEST_OPERATIONS_ADMIN               |
| 0f03cd045f8141f7bbbb0bc82b02f89f | REQUEST_ORG_ADMIN                      |
| 592bdcbaec5a44a9940a26f10b98a449 | REQUEST_USER                           |
| 744051fc542d4bf39f773861dab37240 | SERVICE_INSTANCES_ADMIN                |
| 92230f90a1bb41ad935e648b1e503a40 | SERVICE_INSTANCES_ADMIN_READER         |
| 37e0291de03b4736910547932962a114 | SERVICE_INSTANCES_CUSTOMER_ORG_ADMIN   |
| ceb7265b5f6c4fef8954bfd15626cb48 | SERVICE_INSTANCES_DEPARTMENT_ADMIN     |
| 2c5212d9a2fb4b4c9784e3f25e4aa0fa | SERVICE_INSTANCES_DEPARTMENT_USER      |
| f06c5b57e5fa4381b11d892e14791020 | SERVICE_INSTANCES_OPERATIONS_ADMIN     |
| 6b01afdf7be44d32abf2aa33af203d8b | SERVICE_INSTANCES_ORG_ADMIN            |
| 42a1455e4367416ab29d1fad3c2973dc | SERVICE_INSTANCES_USER                 |
| 219ac0f3b7e04963832866503978e023 | SERVICE_USER                           |
| ea7223333fe841cc85836b40641bb49f | TERRAFORM_USER                         |
| 2331bed60b5b4e5ebfb7448b20d3e0d9 | TICKETING_ADMIN                        |
| 378896ded19d4524a2cef9323308e1e9 | TICKETING_CUSTOMER_ORG_ADMIN           |
| 873c8ac0cbe04eb48c03fa365934cb5c | TICKETING_ORG_ADMIN                    |
| 0cb1564f804a41039b4b8c1f1166ba38 | TICKETING_USER                         |
| b0700f44993248dc84903e9bd4fdc62d | admin                                  |
| fa6c756fa0dd43b7b5c35ab7b284177c | member                                 |
| 09cf3d592e784e84b892cf6b4f952d93 | reader                                 |
+----------------------------------+----------------------------------------+
Check role implications:
openstack implied role list
Implied role list example
Implied roles
+----------------------------------+---------------------------------------+---------------------------------
+----------------------------------------+
| Prior Role ID                    | Prior Role Name                       | Implied Role ID                  | 
Implied Role Name                      |
+----------------------------------+---------------------------------------+---------------------------------
+----------------------------------------+
| 0c51d214e5d443f8974939b6b06b20f2 | BUSINESS_ADAPTER_ADMIN                | 00ce711c813b4ce78a8b3d0d81e217fb | 
BLOB_STORE_ADMIN                       |
| 0c51d214e5d443f8974939b6b06b20f2 | BUSINESS_ADAPTER_ADMIN                | 01da55484b4443b589bf97c9a40dd564 | 
CATALOG_USER                           |
| 0c51d214e5d443f8974939b6b06b20f2 | BUSINESS_ADAPTER_ADMIN                | 0bff31bbb41e4357921887776b1b2f5f | 
CONFIG_ADMIN_READER                    |
| 0c51d214e5d443f8974939b6b06b20f2 | BUSINESS_ADAPTER_ADMIN                | 171b9c75bf6f468c9209f14bd8a24d08 | 
SERVICE_INSTANCES_USER                 |
| 0c51d214e5d443f8974939b6b06b20f2 | BUSINESS_ADAPTER_ADMIN                | 293ff25baf6242118930c7c0147d7e08 | 
DIAGNOSTIC_ADMIN                       |
| 0c51d214e5d443f8974939b6b06b20f2 | BUSINESS_ADAPTER_ADMIN                | 2dc0b208f8db4033b91f0190ffb16418 | 
REPORTING_ADMIN                        |
| 0c51d214e5d443f8974939b6b06b20f2 | BUSINESS_ADAPTER_ADMIN                | 2e55d1678c994da99905b350af6d05f3 | 
FULFILLMENT_ADAPTER_ADMIN              |
| 0c51d214e5d443f8974939b6b06b20f2 | BUSINESS_ADAPTER_ADMIN                | 65e6d45d3dab4cc3802df30f38178dd2 | 
CUSTOMERS_ADMIN_READER                 |
| 0c51d214e5d443f8974939b6b06b20f2 | BUSINESS_ADAPTER_ADMIN                | 69326c250e0e440e89e661d05725371f | 
CATALOG_ADMIN_READER                   |
| 0c51d214e5d443f8974939b6b06b20f2 | BUSINESS_ADAPTER_ADMIN                | 776a6db1eccd4b8d9dd6d10a28f2f34f | 
EVENT_ADMIN                            |
| 0c51d214e5d443f8974939b6b06b20f2 | BUSINESS_ADAPTER_ADMIN                | 80f6a6e604d94e9a98a8d7d78be9db62 | 
PRICING_ADMIN_READER                   |
| 0c51d214e5d443f8974939b6b06b20f2 | BUSINESS_ADAPTER_ADMIN                | 838875cef19c4fbfa470a60fd73d5ff5 | 
PRICING_USER                           |
| 0c51d214e5d443f8974939b6b06b20f2 | BUSINESS_ADAPTER_ADMIN                | 852136a803c44853b8acbdf22df92d4f | 
REQUEST_USER                           |
| 0c51d214e5d443f8974939b6b06b20f2 | BUSINESS_ADAPTER_ADMIN                | 8a099b8959574764a26150e472ab7257 | 
REQUEST_ADMIN_READER                   |
| 0c51d214e5d443f8974939b6b06b20f2 | BUSINESS_ADAPTER_ADMIN                | a92f09b4fde344b2bf1b49a44925af7f | 
FULFILLMENT_USER                       |
| 0c51d214e5d443f8974939b6b06b20f2 | BUSINESS_ADAPTER_ADMIN                | b29f14fefb1a466386ba6e980f3effc1 | 
TICKETING_USER                         |
| 0c51d214e5d443f8974939b6b06b20f2 | BUSINESS_ADAPTER_ADMIN                | b3277e2971ca4929b0250cbc5b39dbb7 | 
CUSTOMERS_USER                         |
| 0c51d214e5d443f8974939b6b06b20f2 | BUSINESS_ADAPTER_ADMIN                | c3a4fb2994c042d48c482dd2529398a0 | 
FULFILLMENT_ADMIN_READER               |
| 0c51d214e5d443f8974939b6b06b20f2 | BUSINESS_ADAPTER_ADMIN                | c69a74d231fa42c8bb77436db3963321 | 
BLOB_STORE_USER                        |
| 0c51d214e5d443f8974939b6b06b20f2 | BUSINESS_ADAPTER_ADMIN                | cf2956f6961b4ed7ad15db22fd476605 | 
CONFIG_ADAPTER_ADMIN                   |
| 0c51d214e5d443f8974939b6b06b20f2 | BUSINESS_ADAPTER_ADMIN                | e3bad820c1af493589bc2c79b4fc3f06 | 
EXPORT_IMPORT_USER                     |
| 0c51d214e5d443f8974939b6b06b20f2 | BUSINESS_ADAPTER_ADMIN                | f543134ecd324456bd0edc71be62447f | 
TICKETING_ADMIN                        |
| 0c51d214e5d443f8974939b6b06b20f2 | BUSINESS_ADAPTER_ADMIN                | f6ec013257d54e4a93ca64ba20e1f993 | 
SERVICE_INSTANCES_ADMIN_READER         |
| 0e1bcb8f99b841d49c654a3793748b35 | BUSINESS_ADMIN                        | 00ce711c813b4ce78a8b3d0d81e217fb | 
BLOB_STORE_ADMIN                       |
| 0e1bcb8f99b841d49c654a3793748b35 | BUSINESS_ADMIN                        | 01da55484b4443b589bf97c9a40dd564 | 
CATALOG_USER                           |
| 0e1bcb8f99b841d49c654a3793748b35 | BUSINESS_ADMIN                        | 0bff31bbb41e4357921887776b1b2f5f | 
CONFIG_ADMIN_READER                    |
| 0e1bcb8f99b841d49c654a3793748b35 | BUSINESS_ADMIN                        | 0fcccab73e4f4621b09e8073eec99bb6 | 
FULFILLMENT_ADMIN                      |
| 0e1bcb8f99b841d49c654a3793748b35 | BUSINESS_ADMIN                        | 171b9c75bf6f468c9209f14bd8a24d08 | 
SERVICE_INSTANCES_USER                 |
| 0e1bcb8f99b841d49c654a3793748b35 | BUSINESS_ADMIN                        | 293ff25baf6242118930c7c0147d7e08 | 
DIAGNOSTIC_ADMIN                       |
| 0e1bcb8f99b841d49c654a3793748b35 | BUSINESS_ADMIN                        | 2dc0b208f8db4033b91f0190ffb16418 | 
REPORTING_ADMIN                        |
| 0e1bcb8f99b841d49c654a3793748b35 | BUSINESS_ADMIN                        | 48816f58a56f45ba9285f024b20e3362 | 
REQUEST_ADMIN                          |
| 0e1bcb8f99b841d49c654a3793748b35 | BUSINESS_ADMIN                        | 5188943501094f91bae6aa71e2ab3f92 | 
SERVICE_INSTANCES_ADMIN                |
| 0e1bcb8f99b841d49c654a3793748b35 | BUSINESS_ADMIN                        | 673ce1663c27459382ddb0a25dae86ab | 
CONFIG_CUSTOMER_ADMIN                  |
| 0e1bcb8f99b841d49c654a3793748b35 | BUSINESS_ADMIN                        | 776a6db1eccd4b8d9dd6d10a28f2f34f | 
EVENT_ADMIN                            |
| 0e1bcb8f99b841d49c654a3793748b35 | BUSINESS_ADMIN                        | 7a953225d1234e1ca5b6b65b0f689798 | 
CATALOG_ADMIN                          |
| 0e1bcb8f99b841d49c654a3793748b35 | BUSINESS_ADMIN                        | 838875cef19c4fbfa470a60fd73d5ff5 | 
PRICING_USER                           |
| 0e1bcb8f99b841d49c654a3793748b35 | BUSINESS_ADMIN                        | 852136a803c44853b8acbdf22df92d4f | 
REQUEST_USER                           |
| 0e1bcb8f99b841d49c654a3793748b35 | BUSINESS_ADMIN                        | 955fdf2f096e409e914253817f0e1b43 | 
PRICING_ADMIN                          |
| 0e1bcb8f99b841d49c654a3793748b35 | BUSINESS_ADMIN                        | a92f09b4fde344b2bf1b49a44925af7f | 
FULFILLMENT_USER                       |
| 0e1bcb8f99b841d49c654a3793748b35 | BUSINESS_ADMIN                        | b29f14fefb1a466386ba6e980f3effc1 | 
TICKETING_USER                         |
| 0e1bcb8f99b841d49c654a3793748b35 | BUSINESS_ADMIN                        | b3277e2971ca4929b0250cbc5b39dbb7 | 
CUSTOMERS_USER                         |
| 0e1bcb8f99b841d49c654a3793748b35 | BUSINESS_ADMIN                        | c69a74d231fa42c8bb77436db3963321 | 
BLOB_STORE_USER                        |
| 0e1bcb8f99b841d49c654a3793748b35 | BUSINESS_ADMIN                        | cf2956f6961b4ed7ad15db22fd476605 | 
CONFIG_ADAPTER_ADMIN                   |
| 0e1bcb8f99b841d49c654a3793748b35 | BUSINESS_ADMIN                        | e555ca1d6a724241a6d99fe27bfecaf0 | 
CUSTOMERS_ADMIN                        |
| 0e1bcb8f99b841d49c654a3793748b35 | BUSINESS_ADMIN                        | f543134ecd324456bd0edc71be62447f | 
TICKETING_ADMIN                        |
| 62325ae7af4549b5aa8449b3b93ade23 | BUSINESS_PRICING_ADMIN                | 00ce711c813b4ce78a8b3d0d81e217fb | 
BLOB_STORE_ADMIN                       |
| 62325ae7af4549b5aa8449b3b93ade23 | BUSINESS_PRICING_ADMIN                | 01da55484b4443b589bf97c9a40dd564 | 
CATALOG_USER                           |
| 62325ae7af4549b5aa8449b3b93ade23 | BUSINESS_PRICING_ADMIN                | 0bff31bbb41e4357921887776b1b2f5f | 
CONFIG_ADMIN_READER                    |
| 62325ae7af4549b5aa8449b3b93ade23 | BUSINESS_PRICING_ADMIN                | 171b9c75bf6f468c9209f14bd8a24d08 | 
SERVICE_INSTANCES_USER                 |
| 62325ae7af4549b5aa8449b3b93ade23 | BUSINESS_PRICING_ADMIN                | 293ff25baf6242118930c7c0147d7e08 | 
DIAGNOSTIC_ADMIN                       |
| 62325ae7af4549b5aa8449b3b93ade23 | BUSINESS_PRICING_ADMIN                | 2dc0b208f8db4033b91f0190ffb16418 | 
REPORTING_ADMIN                        |
| 62325ae7af4549b5aa8449b3b93ade23 | BUSINESS_PRICING_ADMIN                | 65e6d45d3dab4cc3802df30f38178dd2 | 
CUSTOMERS_ADMIN_READER                 |
| 62325ae7af4549b5aa8449b3b93ade23 | BUSINESS_PRICING_ADMIN                | 69326c250e0e440e89e661d05725371f | 
CATALOG_ADMIN_READER                   |
| 62325ae7af4549b5aa8449b3b93ade23 | BUSINESS_PRICING_ADMIN                | 776a6db1eccd4b8d9dd6d10a28f2f34f | 
EVENT_ADMIN                            |
| 62325ae7af4549b5aa8449b3b93ade23 | BUSINESS_PRICING_ADMIN                | 80f6a6e604d94e9a98a8d7d78be9db62 | 
PRICING_ADMIN_READER                   |
| 62325ae7af4549b5aa8449b3b93ade23 | BUSINESS_PRICING_ADMIN                | 838875cef19c4fbfa470a60fd73d5ff5 | 
PRICING_USER                           |
| 62325ae7af4549b5aa8449b3b93ade23 | BUSINESS_PRICING_ADMIN                | 852136a803c44853b8acbdf22df92d4f | 
REQUEST_USER                           |
| 62325ae7af4549b5aa8449b3b93ade23 | BUSINESS_PRICING_ADMIN                | 8a099b8959574764a26150e472ab7257 | 
REQUEST_ADMIN_READER                   |
| 62325ae7af4549b5aa8449b3b93ade23 | BUSINESS_PRICING_ADMIN                | 955fdf2f096e409e914253817f0e1b43 | 
PRICING_ADMIN                          |
| 62325ae7af4549b5aa8449b3b93ade23 | BUSINESS_PRICING_ADMIN                | 9595a2fc9721414e9e7fdb9dd7b3bb68 | 
FULFILLMENT_PRICING_ADMIN              |
| 62325ae7af4549b5aa8449b3b93ade23 | BUSINESS_PRICING_ADMIN                | a92f09b4fde344b2bf1b49a44925af7f | 
FULFILLMENT_USER                       |
| 62325ae7af4549b5aa8449b3b93ade23 | BUSINESS_PRICING_ADMIN                | b29f14fefb1a466386ba6e980f3effc1 | 
TICKETING_USER                         |
| 62325ae7af4549b5aa8449b3b93ade23 | BUSINESS_PRICING_ADMIN                | b3277e2971ca4929b0250cbc5b39dbb7 | 
CUSTOMERS_USER                         |
| 62325ae7af4549b5aa8449b3b93ade23 | BUSINESS_PRICING_ADMIN                | c3a4fb2994c042d48c482dd2529398a0 | 
FULFILLMENT_ADMIN_READER               |
| 62325ae7af4549b5aa8449b3b93ade23 | BUSINESS_PRICING_ADMIN                | c69a74d231fa42c8bb77436db3963321 | 
BLOB_STORE_USER                        |
| 62325ae7af4549b5aa8449b3b93ade23 | BUSINESS_PRICING_ADMIN                | df7b49633f5f4eb5b764f6e34ec10d43 | 
CATALOG_PRICING_ADMIN                  |
| 62325ae7af4549b5aa8449b3b93ade23 | BUSINESS_PRICING_ADMIN                | f543134ecd324456bd0edc71be62447f | 
TICKETING_ADMIN                        |
| 62325ae7af4549b5aa8449b3b93ade23 | BUSINESS_PRICING_ADMIN                | f6ec013257d54e4a93ca64ba20e1f993 | 
SERVICE_INSTANCES_ADMIN_READER         |
| 97bebdd8bfe74fada864c1a26bad80f0 | BUSINESS_CUSTOMER_ADMIN               | 00ce711c813b4ce78a8b3d0d81e217fb | 
BLOB_STORE_ADMIN                       |
| 97bebdd8bfe74fada864c1a26bad80f0 | BUSINESS_CUSTOMER_ADMIN               | 01da55484b4443b589bf97c9a40dd564 | 
CATALOG_USER                           |
| 97bebdd8bfe74fada864c1a26bad80f0 | BUSINESS_CUSTOMER_ADMIN               | 0bff31bbb41e4357921887776b1b2f5f | 
CONFIG_ADMIN_READER                    |
| 97bebdd8bfe74fada864c1a26bad80f0 | BUSINESS_CUSTOMER_ADMIN               | 171b9c75bf6f468c9209f14bd8a24d08 | 
SERVICE_INSTANCES_USER                 |
| 97bebdd8bfe74fada864c1a26bad80f0 | BUSINESS_CUSTOMER_ADMIN               | 293ff25baf6242118930c7c0147d7e08 | 
DIAGNOSTIC_ADMIN                       |
| 97bebdd8bfe74fada864c1a26bad80f0 | BUSINESS_CUSTOMER_ADMIN               | 2dc0b208f8db4033b91f0190ffb16418 | 
REPORTING_ADMIN                        |
| 97bebdd8bfe74fada864c1a26bad80f0 | BUSINESS_CUSTOMER_ADMIN               | 6000fa6db5d843839398ff32a6284d89 | 
FULFILLMENT_CUSTOMER_ADMIN             |
| 97bebdd8bfe74fada864c1a26bad80f0 | BUSINESS_CUSTOMER_ADMIN               | 65e6d45d3dab4cc3802df30f38178dd2 | 
CUSTOMERS_ADMIN_READER                 |
| 97bebdd8bfe74fada864c1a26bad80f0 | BUSINESS_CUSTOMER_ADMIN               | 673ce1663c27459382ddb0a25dae86ab | 
CONFIG_CUSTOMER_ADMIN                  |
| 97bebdd8bfe74fada864c1a26bad80f0 | BUSINESS_CUSTOMER_ADMIN               | 69326c250e0e440e89e661d05725371f | 
CATALOG_ADMIN_READER                   |
| 97bebdd8bfe74fada864c1a26bad80f0 | BUSINESS_CUSTOMER_ADMIN               | 776a6db1eccd4b8d9dd6d10a28f2f34f | 
EVENT_ADMIN                            |
| 97bebdd8bfe74fada864c1a26bad80f0 | BUSINESS_CUSTOMER_ADMIN               | 80f6a6e604d94e9a98a8d7d78be9db62 | 
PRICING_ADMIN_READER                   |
| 97bebdd8bfe74fada864c1a26bad80f0 | BUSINESS_CUSTOMER_ADMIN               | 838875cef19c4fbfa470a60fd73d5ff5 | 
PRICING_USER                           |
| 97bebdd8bfe74fada864c1a26bad80f0 | BUSINESS_CUSTOMER_ADMIN               | 852136a803c44853b8acbdf22df92d4f | 
REQUEST_USER                           |
| 97bebdd8bfe74fada864c1a26bad80f0 | BUSINESS_CUSTOMER_ADMIN               | 8a099b8959574764a26150e472ab7257 | 
REQUEST_ADMIN_READER                   |
| 97bebdd8bfe74fada864c1a26bad80f0 | BUSINESS_CUSTOMER_ADMIN               | a92f09b4fde344b2bf1b49a44925af7f | 
FULFILLMENT_USER                       |
| 97bebdd8bfe74fada864c1a26bad80f0 | BUSINESS_CUSTOMER_ADMIN               | b29f14fefb1a466386ba6e980f3effc1 | 
TICKETING_USER                         |
| 97bebdd8bfe74fada864c1a26bad80f0 | BUSINESS_CUSTOMER_ADMIN               | b3277e2971ca4929b0250cbc5b39dbb7 | 
CUSTOMERS_USER                         |
| 97bebdd8bfe74fada864c1a26bad80f0 | BUSINESS_CUSTOMER_ADMIN               | c3a4fb2994c042d48c482dd2529398a0 | 
FULFILLMENT_ADMIN_READER               |
| 97bebdd8bfe74fada864c1a26bad80f0 | BUSINESS_CUSTOMER_ADMIN               | c69a74d231fa42c8bb77436db3963321 | 
BLOB_STORE_USER                        |
| 97bebdd8bfe74fada864c1a26bad80f0 | BUSINESS_CUSTOMER_ADMIN               | e555ca1d6a724241a6d99fe27bfecaf0 | 
CUSTOMERS_ADMIN                        |
| 97bebdd8bfe74fada864c1a26bad80f0 | BUSINESS_CUSTOMER_ADMIN               | f543134ecd324456bd0edc71be62447f | 
TICKETING_ADMIN                        |
| 97bebdd8bfe74fada864c1a26bad80f0 | BUSINESS_CUSTOMER_ADMIN               | f6ec013257d54e4a93ca64ba20e1f993 | 
SERVICE_INSTANCES_ADMIN_READER         |
| 97bebdd8bfe74fada864c1a26bad80f0 | BUSINESS_CUSTOMER_ADMIN               | ff4b318bcc554796a09073845118b437 | 
CATALOG_CUSTOMER_ADMIN                 |
| a46062eaf6de4824ae0441403542aa56 | BUSINESS_OPERATIONS_ADMIN             | 00ce711c813b4ce78a8b3d0d81e217fb | 
BLOB_STORE_ADMIN                       |
| a46062eaf6de4824ae0441403542aa56 | BUSINESS_OPERATIONS_ADMIN             | 01da55484b4443b589bf97c9a40dd564 | 
CATALOG_USER                           |
| a46062eaf6de4824ae0441403542aa56 | BUSINESS_OPERATIONS_ADMIN             | 0bff31bbb41e4357921887776b1b2f5f | 
CONFIG_ADMIN_READER                    |
| a46062eaf6de4824ae0441403542aa56 | BUSINESS_OPERATIONS_ADMIN             | 171b9c75bf6f468c9209f14bd8a24d08 | 
SERVICE_INSTANCES_USER                 |
| a46062eaf6de4824ae0441403542aa56 | BUSINESS_OPERATIONS_ADMIN             | 293ff25baf6242118930c7c0147d7e08 | 
DIAGNOSTIC_ADMIN                       |
| a46062eaf6de4824ae0441403542aa56 | BUSINESS_OPERATIONS_ADMIN             | 2dc0b208f8db4033b91f0190ffb16418 | 
REPORTING_ADMIN                        |
| a46062eaf6de4824ae0441403542aa56 | BUSINESS_OPERATIONS_ADMIN             | 590157f684f74e52a97f7706e226b84d | 
SERVICE_INSTANCES_OPERATIONS_ADMIN     |
| a46062eaf6de4824ae0441403542aa56 | BUSINESS_OPERATIONS_ADMIN             | 65e6d45d3dab4cc3802df30f38178dd2 | 
CUSTOMERS_ADMIN_READER                 |
| a46062eaf6de4824ae0441403542aa56 | BUSINESS_OPERATIONS_ADMIN             | 69326c250e0e440e89e661d05725371f | 
CATALOG_ADMIN_READER                   |
| a46062eaf6de4824ae0441403542aa56 | BUSINESS_OPERATIONS_ADMIN             | 776a6db1eccd4b8d9dd6d10a28f2f34f | 
EVENT_ADMIN                            |
| a46062eaf6de4824ae0441403542aa56 | BUSINESS_OPERATIONS_ADMIN             | 80f6a6e604d94e9a98a8d7d78be9db62 | 
PRICING_ADMIN_READER                   |
| a46062eaf6de4824ae0441403542aa56 | BUSINESS_OPERATIONS_ADMIN             | 838875cef19c4fbfa470a60fd73d5ff5 | 
PRICING_USER                           |
| a46062eaf6de4824ae0441403542aa56 | BUSINESS_OPERATIONS_ADMIN             | 852136a803c44853b8acbdf22df92d4f | 
REQUEST_USER                           |
| a46062eaf6de4824ae0441403542aa56 | BUSINESS_OPERATIONS_ADMIN             | 8a099b8959574764a26150e472ab7257 | 
REQUEST_ADMIN_READER                   |
| a46062eaf6de4824ae0441403542aa56 | BUSINESS_OPERATIONS_ADMIN             | a3c4fa54c10f463abe62cd59ec12690b | 
FULFILLMENT_OPERATIONS_ADMIN           |
| a46062eaf6de4824ae0441403542aa56 | BUSINESS_OPERATIONS_ADMIN             | a692b64c3d964a9b8d098806cb1e7311 | 
REQUEST_OPERATIONS_ADMIN               |
| a46062eaf6de4824ae0441403542aa56 | BUSINESS_OPERATIONS_ADMIN             | a92f09b4fde344b2bf1b49a44925af7f | 
FULFILLMENT_USER                       |
| a46062eaf6de4824ae0441403542aa56 | BUSINESS_OPERATIONS_ADMIN             | b29f14fefb1a466386ba6e980f3effc1 | 
TICKETING_USER                         |
| a46062eaf6de4824ae0441403542aa56 | BUSINESS_OPERATIONS_ADMIN             | b3277e2971ca4929b0250cbc5b39dbb7 | 
CUSTOMERS_USER                         |
| a46062eaf6de4824ae0441403542aa56 | BUSINESS_OPERATIONS_ADMIN             | c3a4fb2994c042d48c482dd2529398a0 | 
FULFILLMENT_ADMIN_READER               |
| a46062eaf6de4824ae0441403542aa56 | BUSINESS_OPERATIONS_ADMIN             | c69a74d231fa42c8bb77436db3963321 | 
BLOB_STORE_USER                        |
| a46062eaf6de4824ae0441403542aa56 | BUSINESS_OPERATIONS_ADMIN             | f543134ecd324456bd0edc71be62447f | 
TICKETING_ADMIN                        |
| a46062eaf6de4824ae0441403542aa56 | BUSINESS_OPERATIONS_ADMIN             | f6ec013257d54e4a93ca64ba20e1f993 | 
SERVICE_INSTANCES_ADMIN_READER         |
| fe72166733f642d3ba3930ca3fa4aeae | BUSINESS_CATALOG_ADMIN                | 00ce711c813b4ce78a8b3d0d81e217fb | 
BLOB_STORE_ADMIN                       |
| fe72166733f642d3ba3930ca3fa4aeae | BUSINESS_CATALOG_ADMIN                | 01da55484b4443b589bf97c9a40dd564 | 
CATALOG_USER                           |
| fe72166733f642d3ba3930ca3fa4aeae | BUSINESS_CATALOG_ADMIN                | 0bff31bbb41e4357921887776b1b2f5f | 
CONFIG_ADMIN_READER                    |
| fe72166733f642d3ba3930ca3fa4aeae | BUSINESS_CATALOG_ADMIN                | 171b9c75bf6f468c9209f14bd8a24d08 | 
SERVICE_INSTANCES_USER                 |
| fe72166733f642d3ba3930ca3fa4aeae | BUSINESS_CATALOG_ADMIN                | 293ff25baf6242118930c7c0147d7e08 | 
DIAGNOSTIC_ADMIN                       |
| fe72166733f642d3ba3930ca3fa4aeae | BUSINESS_CATALOG_ADMIN                | 2dc0b208f8db4033b91f0190ffb16418 | 
REPORTING_ADMIN                        |
| fe72166733f642d3ba3930ca3fa4aeae | BUSINESS_CATALOG_ADMIN                | 65e6d45d3dab4cc3802df30f38178dd2 | 
CUSTOMERS_ADMIN_READER                 |
| fe72166733f642d3ba3930ca3fa4aeae | BUSINESS_CATALOG_ADMIN                | 69326c250e0e440e89e661d05725371f | 
CATALOG_ADMIN_READER                   |
| fe72166733f642d3ba3930ca3fa4aeae | BUSINESS_CATALOG_ADMIN                | 776a6db1eccd4b8d9dd6d10a28f2f34f | 
EVENT_ADMIN                            |
| fe72166733f642d3ba3930ca3fa4aeae | BUSINESS_CATALOG_ADMIN                | 7a953225d1234e1ca5b6b65b0f689798 | 
CATALOG_ADMIN                          |
| fe72166733f642d3ba3930ca3fa4aeae | BUSINESS_CATALOG_ADMIN                | 80f6a6e604d94e9a98a8d7d78be9db62 | 
PRICING_ADMIN_READER                   |
| fe72166733f642d3ba3930ca3fa4aeae | BUSINESS_CATALOG_ADMIN                | 838875cef19c4fbfa470a60fd73d5ff5 | 
PRICING_USER                           |
| fe72166733f642d3ba3930ca3fa4aeae | BUSINESS_CATALOG_ADMIN                | 852136a803c44853b8acbdf22df92d4f | 
REQUEST_USER                           |
| fe72166733f642d3ba3930ca3fa4aeae | BUSINESS_CATALOG_ADMIN                | 8a099b8959574764a26150e472ab7257 | 
REQUEST_ADMIN_READER                   |
| fe72166733f642d3ba3930ca3fa4aeae | BUSINESS_CATALOG_ADMIN                | 96acd2149ef746a5a49c867590f9303d | 
FULFILLMENT_DESIGN_ADMIN               |
| fe72166733f642d3ba3930ca3fa4aeae | BUSINESS_CATALOG_ADMIN                | a92f09b4fde344b2bf1b49a44925af7f | 
FULFILLMENT_USER                       |
| fe72166733f642d3ba3930ca3fa4aeae | BUSINESS_CATALOG_ADMIN                | b29f14fefb1a466386ba6e980f3effc1 | 
TICKETING_USER                         |
| fe72166733f642d3ba3930ca3fa4aeae | BUSINESS_CATALOG_ADMIN                | b3277e2971ca4929b0250cbc5b39dbb7 | 
CUSTOMERS_USER                         |
| fe72166733f642d3ba3930ca3fa4aeae | BUSINESS_CATALOG_ADMIN                | c3a4fb2994c042d48c482dd2529398a0 | 
FULFILLMENT_ADMIN_READER               |
| fe72166733f642d3ba3930ca3fa4aeae | BUSINESS_CATALOG_ADMIN                | c69a74d231fa42c8bb77436db3963321 | 
BLOB_STORE_USER                        |
| fe72166733f642d3ba3930ca3fa4aeae | BUSINESS_CATALOG_ADMIN                | f543134ecd324456bd0edc71be62447f | 
TICKETING_ADMIN                        |
| fe72166733f642d3ba3930ca3fa4aeae | BUSINESS_CATALOG_ADMIN                | f6ec013257d54e4a93ca64ba20e1f993 | 
SERVICE_INSTANCES_ADMIN_READER         |
| bd3eb030f6434dcc811048587b1fb12d | BUSINESS_CUSTOMER_END_USER            | 01da55484b4443b589bf97c9a40dd564 | 
CATALOG_USER                           |
| bd3eb030f6434dcc811048587b1fb12d | BUSINESS_CUSTOMER_END_USER            | 171b9c75bf6f468c9209f14bd8a24d08 | 
SERVICE_INSTANCES_USER                 |
| bd3eb030f6434dcc811048587b1fb12d | BUSINESS_CUSTOMER_END_USER            | 29e1056f7c394e68a45ce4c598a30ef0 | 
CATALOG_CONSUMER                       |
| bd3eb030f6434dcc811048587b1fb12d | BUSINESS_CUSTOMER_END_USER            | 838875cef19c4fbfa470a60fd73d5ff5 | 
PRICING_USER                           |
| bd3eb030f6434dcc811048587b1fb12d | BUSINESS_CUSTOMER_END_USER            | 852136a803c44853b8acbdf22df92d4f | 
REQUEST_USER                           |
| bd3eb030f6434dcc811048587b1fb12d | BUSINESS_CUSTOMER_END_USER            | a92f09b4fde344b2bf1b49a44925af7f | 
FULFILLMENT_USER                       |
| bd3eb030f6434dcc811048587b1fb12d | BUSINESS_CUSTOMER_END_USER            | b29f14fefb1a466386ba6e980f3effc1 | 
TICKETING_USER                         |
| bd3eb030f6434dcc811048587b1fb12d | BUSINESS_CUSTOMER_END_USER            | b3277e2971ca4929b0250cbc5b39dbb7 | 
CUSTOMERS_USER                         |
| bd3eb030f6434dcc811048587b1fb12d | BUSINESS_CUSTOMER_END_USER            | c69a74d231fa42c8bb77436db3963321 | 
BLOB_STORE_USER                        |
| bd3eb030f6434dcc811048587b1fb12d | BUSINESS_CUSTOMER_END_USER            | c76001fb35c14155bf7b3ec9979726f3 | 
REPORTING_USER                         |
| bd3eb030f6434dcc811048587b1fb12d | BUSINESS_CUSTOMER_END_USER            | f6f2e90ac3154955af365cc30b05e112 | 
REQUEST_CONSUMER                       |
| eedd3004f5734ff0a4ea517279cc1687 | BUSINESS_ORG_ADMIN                    | 01da55484b4443b589bf97c9a40dd564 | 
CATALOG_USER                           |
| eedd3004f5734ff0a4ea517279cc1687 | BUSINESS_ORG_ADMIN                    | 123da6b3d3a94e7ebe40a82bc1c808a7 | 
CUSTOMERS_ORG_ADMIN                    |
| eedd3004f5734ff0a4ea517279cc1687 | BUSINESS_ORG_ADMIN                    | 171b9c75bf6f468c9209f14bd8a24d08 | 
SERVICE_INSTANCES_USER                 |
| eedd3004f5734ff0a4ea517279cc1687 | BUSINESS_ORG_ADMIN                    | 5333eb1816f74120a7e0794f63418347 | 
REPORTING_ORG_ADMIN                    |
| eedd3004f5734ff0a4ea517279cc1687 | BUSINESS_ORG_ADMIN                    | 8289ec9ad6fa43e68b8b8005f2efa091 | 
FULFILLMENT_ORG_ADMIN                  |
| eedd3004f5734ff0a4ea517279cc1687 | BUSINESS_ORG_ADMIN                    | 838875cef19c4fbfa470a60fd73d5ff5 | 
PRICING_USER                           |
| eedd3004f5734ff0a4ea517279cc1687 | BUSINESS_ORG_ADMIN                    | 852136a803c44853b8acbdf22df92d4f | 
REQUEST_USER                           |
| eedd3004f5734ff0a4ea517279cc1687 | BUSINESS_ORG_ADMIN                    | 8acf0de82e5e4d91bf093f0ee208ef2a | 
REQUEST_ORG_ADMIN                      |
| eedd3004f5734ff0a4ea517279cc1687 | BUSINESS_ORG_ADMIN                    | 8f6bb73bd63642eb80ea35a0b928dd45 | 
PRICING_ORG_ADMIN                      |
| eedd3004f5734ff0a4ea517279cc1687 | BUSINESS_ORG_ADMIN                    | 8f6d0d399061465d92350621b97b24f7 | 
SERVICE_INSTANCES_ORG_ADMIN            |
| eedd3004f5734ff0a4ea517279cc1687 | BUSINESS_ORG_ADMIN                    | a92f09b4fde344b2bf1b49a44925af7f | 
FULFILLMENT_USER                       |
| eedd3004f5734ff0a4ea517279cc1687 | BUSINESS_ORG_ADMIN                    | ab825fdc8c934847b21093bbd32df3ed | 
TICKETING_ORG_ADMIN                    |
| eedd3004f5734ff0a4ea517279cc1687 | BUSINESS_ORG_ADMIN                    | b29f14fefb1a466386ba6e980f3effc1 | 
TICKETING_USER                         |
| eedd3004f5734ff0a4ea517279cc1687 | BUSINESS_ORG_ADMIN                    | b3277e2971ca4929b0250cbc5b39dbb7 | 
CUSTOMERS_USER                         |
| eedd3004f5734ff0a4ea517279cc1687 | BUSINESS_ORG_ADMIN                    | b9096736bde541b096a19531f05a2412 | 
CATALOG_ORG_ADMIN                      |
| eedd3004f5734ff0a4ea517279cc1687 | BUSINESS_ORG_ADMIN                    | c69a74d231fa42c8bb77436db3963321 | 
BLOB_STORE_USER                        |
| eedd3004f5734ff0a4ea517279cc1687 | BUSINESS_ORG_ADMIN                    | fa27678e43b2473788d5da078e242931 | 
BLOB_STORE_ORG_ADMIN                   |
| fe6968db07434467a6c6b7d9b66f8fb8 | BUSINESS_CUSTOMER_ORG_ADMIN           | 01da55484b4443b589bf97c9a40dd564 | 
CATALOG_USER                           |
| fe6968db07434467a6c6b7d9b66f8fb8 | BUSINESS_CUSTOMER_ORG_ADMIN           | 0cda802d4dda4f238e7d6722ef996452 | 
REQUEST_CUSTOMER_ORG_ADMIN             |
| fe6968db07434467a6c6b7d9b66f8fb8 | BUSINESS_CUSTOMER_ORG_ADMIN           | 171b9c75bf6f468c9209f14bd8a24d08 | 
SERVICE_INSTANCES_USER                 |
| fe6968db07434467a6c6b7d9b66f8fb8 | BUSINESS_CUSTOMER_ORG_ADMIN           | 2b7866015399430c9238e37c4e2878af | 
FULFILLMENT_CUSTOMER_ORG_ADMIN         |
| fe6968db07434467a6c6b7d9b66f8fb8 | BUSINESS_CUSTOMER_ORG_ADMIN           | 2da9791363aa4f958e35d55c58897dfd | 
PRICING_CUSTOMER_ORG_ADMIN             |
| fe6968db07434467a6c6b7d9b66f8fb8 | BUSINESS_CUSTOMER_ORG_ADMIN           | 502f420d3b574a1284859af0c7562ded | 
CUSTOMERS_CUSTOMER_ORG_ADMIN           |
| fe6968db07434467a6c6b7d9b66f8fb8 | BUSINESS_CUSTOMER_ORG_ADMIN           | 51a0b7f4f8b148b48e7732af4f312221 | 
TERRAFORM_USER                         |
| fe6968db07434467a6c6b7d9b66f8fb8 | BUSINESS_CUSTOMER_ORG_ADMIN           | 5333eb1816f74120a7e0794f63418347 | 
REPORTING_ORG_ADMIN                    |
| fe6968db07434467a6c6b7d9b66f8fb8 | BUSINESS_CUSTOMER_ORG_ADMIN           | 6c85e427555a4dffbe4e7a06aa1f70b0 | 
TICKETING_CUSTOMER_ORG_ADMIN           |
| fe6968db07434467a6c6b7d9b66f8fb8 | BUSINESS_CUSTOMER_ORG_ADMIN           | 838875cef19c4fbfa470a60fd73d5ff5 | 
PRICING_USER                           |
| fe6968db07434467a6c6b7d9b66f8fb8 | BUSINESS_CUSTOMER_ORG_ADMIN           | 852136a803c44853b8acbdf22df92d4f | 
REQUEST_USER                           |
| fe6968db07434467a6c6b7d9b66f8fb8 | BUSINESS_CUSTOMER_ORG_ADMIN           | 8cfb0ed541b84ad799aca10e140c9d3a | 
ACL_ADMIN                              |
| fe6968db07434467a6c6b7d9b66f8fb8 | BUSINESS_CUSTOMER_ORG_ADMIN           | a92f09b4fde344b2bf1b49a44925af7f | 
FULFILLMENT_USER                       |
| fe6968db07434467a6c6b7d9b66f8fb8 | BUSINESS_CUSTOMER_ORG_ADMIN           | b29f14fefb1a466386ba6e980f3effc1 | 
TICKETING_USER                         |
| fe6968db07434467a6c6b7d9b66f8fb8 | BUSINESS_CUSTOMER_ORG_ADMIN           | b3277e2971ca4929b0250cbc5b39dbb7 | 
CUSTOMERS_USER                         |
| fe6968db07434467a6c6b7d9b66f8fb8 | BUSINESS_CUSTOMER_ORG_ADMIN           | c69a74d231fa42c8bb77436db3963321 | 
BLOB_STORE_USER                        |
| fe6968db07434467a6c6b7d9b66f8fb8 | BUSINESS_CUSTOMER_ORG_ADMIN           | c6a9db53986a40d2add7d4cb4aa10136 | 
SERVICE_INSTANCES_CUSTOMER_ORG_ADMIN   |
| fe6968db07434467a6c6b7d9b66f8fb8 | BUSINESS_CUSTOMER_ORG_ADMIN           | d130c42daca44a29ba808a8b36a94250 | 
BLOB_STORE_CUSTOMER_ORG_ADMIN          |
| fe6968db07434467a6c6b7d9b66f8fb8 | BUSINESS_CUSTOMER_ORG_ADMIN           | f6c55b82653a455287561b1b180bebc4 | 
CATALOG_CUSTOMER_ORG_ADMIN             |
| 0fcccab73e4f4621b09e8073eec99bb6 | FULFILLMENT_ADMIN                     | 0375eb03acd244a081d38ee02e12719d | 
FULFILLMENT_NOTIFIER                   |
| 0fcccab73e4f4621b09e8073eec99bb6 | FULFILLMENT_ADMIN                     | 2e55d1678c994da99905b350af6d05f3 | 
FULFILLMENT_ADAPTER_ADMIN              |
| 0fcccab73e4f4621b09e8073eec99bb6 | FULFILLMENT_ADMIN                     | 6000fa6db5d843839398ff32a6284d89 | 
FULFILLMENT_CUSTOMER_ADMIN             |
| 0fcccab73e4f4621b09e8073eec99bb6 | FULFILLMENT_ADMIN                     | 9595a2fc9721414e9e7fdb9dd7b3bb68 | 
FULFILLMENT_PRICING_ADMIN              |
| 0fcccab73e4f4621b09e8073eec99bb6 | FULFILLMENT_ADMIN                     | 96acd2149ef746a5a49c867590f9303d | 
FULFILLMENT_DESIGN_ADMIN               |
| 0fcccab73e4f4621b09e8073eec99bb6 | FULFILLMENT_ADMIN                     | a3c4fa54c10f463abe62cd59ec12690b | 
FULFILLMENT_OPERATIONS_ADMIN           |
| 0fcccab73e4f4621b09e8073eec99bb6 | FULFILLMENT_ADMIN                     | c3a4fb2994c042d48c482dd2529398a0 | 
FULFILLMENT_ADMIN_READER               |
| f3494030e3f6487c95c23ed81d73e8aa | BUSINESS_DEPARTMENT_ADMIN             | 073940f545554d7ead01d4552ac394ab | 
SERVICE_INSTANCES_DEPARTMENT_ADMIN     |
| f3494030e3f6487c95c23ed81d73e8aa | BUSINESS_DEPARTMENT_ADMIN             | 9c0c2c6abec04dec907da0add52d383f | 
REQUEST_DEPARTMENT_ADMIN               |
| f3494030e3f6487c95c23ed81d73e8aa | BUSINESS_DEPARTMENT_ADMIN             | bd3eb030f6434dcc811048587b1fb12d | 
BUSINESS_CUSTOMER_END_USER             |
| 8cb2a378be314240908efc37e08aa8a3 | CONFIG_ADMIN                          | 0bff31bbb41e4357921887776b1b2f5f | 
CONFIG_ADMIN_READER                    |
| 8cb2a378be314240908efc37e08aa8a3 | CONFIG_ADMIN                          | 673ce1663c27459382ddb0a25dae86ab | 
CONFIG_CUSTOMER_ADMIN                  |
| 8cb2a378be314240908efc37e08aa8a3 | CONFIG_ADMIN                          | cf2956f6961b4ed7ad15db22fd476605 | 
CONFIG_ADAPTER_ADMIN                   |
| ea41d9afed2248758a0b2850f2dafdfd | BUSINESS_SYSTEM_ADMIN                 | 0e1bcb8f99b841d49c654a3793748b35 | 
BUSINESS_ADMIN                         |
| ea41d9afed2248758a0b2850f2dafdfd | BUSINESS_SYSTEM_ADMIN                 | 6904d692e6b648a69cb84fbc6110b44f | 
CUSTOMERS_SYSTEM_ADMIN                 |
| ea41d9afed2248758a0b2850f2dafdfd | BUSINESS_SYSTEM_ADMIN                 | 8cb2a378be314240908efc37e08aa8a3 | 
CONFIG_ADMIN                           |
| ea41d9afed2248758a0b2850f2dafdfd | BUSINESS_SYSTEM_ADMIN                 | 8cfb0ed541b84ad799aca10e140c9d3a | 
ACL_ADMIN                              |
| ea41d9afed2248758a0b2850f2dafdfd | BUSINESS_SYSTEM_ADMIN                 | e3bad820c1af493589bc2c79b4fc3f06 | 
EXPORT_IMPORT_USER                     |
| ea41d9afed2248758a0b2850f2dafdfd | BUSINESS_SYSTEM_ADMIN                 | e5d884f0ac3644698336291817978a7a | 
PRICING_HISTORY_ADMIN                  |
| 0f0e6e3c915e4d5b8b95b758d414f2a3 | BUSINESS_ADM_ACCOUNTS_CUSTOMERS_ADMIN | 296917fe9faa436f916b61563220cdb1 | 
CUSTOMERS_ADM_ACCOUNTS_CUSTOMERS_ADMIN |
| 822e37a18fee4714bba1b6f8224d76c7 | BUSINESS_DEPARTMENT_USER              | 2e4cc74a542c44258f4e2e350c78e0cf | 
SERVICE_INSTANCES_DEPARTMENT_USER      |
| 822e37a18fee4714bba1b6f8224d76c7 | BUSINESS_DEPARTMENT_USER              | 7e963a055606407f9461ccd0c8d9a46b | 
REQUEST_DEPARTMENT_USER                |
| 822e37a18fee4714bba1b6f8224d76c7 | BUSINESS_DEPARTMENT_USER              | bd3eb030f6434dcc811048587b1fb12d | 
BUSINESS_CUSTOMER_END_USER             |
| ead8aa4a393b4f09b6f398c3cab80472 | member                                | 5305e64f84d54eaab618d33b9ba2a9bb | 
reader                                 |
| 2dc0b208f8db4033b91f0190ffb16418 | REPORTING_ADMIN                       | 5333eb1816f74120a7e0794f63418347 | 
REPORTING_ORG_ADMIN                    |
| 5188943501094f91bae6aa71e2ab3f92 | SERVICE_INSTANCES_ADMIN               | 590157f684f74e52a97f7706e226b84d | 
SERVICE_INSTANCES_OPERATIONS_ADMIN     |
| 5188943501094f91bae6aa71e2ab3f92 | SERVICE_INSTANCES_ADMIN               | f6ec013257d54e4a93ca64ba20e1f993 | 
SERVICE_INSTANCES_ADMIN_READER         |
| e555ca1d6a724241a6d99fe27bfecaf0 | CUSTOMERS_ADMIN                       | 65e6d45d3dab4cc3802df30f38178dd2 | 
CUSTOMERS_ADMIN_READER                 |
| 7a953225d1234e1ca5b6b65b0f689798 | CATALOG_ADMIN                         | 69326c250e0e440e89e661d05725371f | 
CATALOG_ADMIN_READER                   |
| 7a953225d1234e1ca5b6b65b0f689798 | CATALOG_ADMIN                         | df7b49633f5f4eb5b764f6e34ec10d43 | 
CATALOG_PRICING_ADMIN                  |
| 7a953225d1234e1ca5b6b65b0f689798 | CATALOG_ADMIN                         | ff4b318bcc554796a09073845118b437 | 
CATALOG_CUSTOMER_ADMIN                 |
| 955fdf2f096e409e914253817f0e1b43 | PRICING_ADMIN                         | 80f6a6e604d94e9a98a8d7d78be9db62 | 
PRICING_ADMIN_READER                   |
| 48816f58a56f45ba9285f024b20e3362 | REQUEST_ADMIN                         | 8a099b8959574764a26150e472ab7257 | 
REQUEST_ADMIN_READER                   |
| 48816f58a56f45ba9285f024b20e3362 | REQUEST_ADMIN                         | a692b64c3d964a9b8d098806cb1e7311 | 
REQUEST_OPERATIONS_ADMIN               |
| 15e7b5b72c3d4f14a02107c4daf30bda | BUSINESS_ACL_ADMIN                    | 8cfb0ed541b84ad799aca10e140c9d3a | 
ACL_ADMIN                              |
| 5333eb1816f74120a7e0794f63418347 | REPORTING_ORG_ADMIN                   | c76001fb35c14155bf7b3ec9979726f3 | 
REPORTING_USER                         |
| daf94f6e37904eff9851ae844146eebc | admin                                 | ead8aa4a393b4f09b6f398c3cab80472 | 
member                                 |
+----------------------------------+---------------------------------------+---------------------------------
+----------------------------------------+
Check users in system domain
openstack user list --domain system --sort-column Name
The user list should look like ...
Created users
+----------------------------------+--------------------+
| ID                               | Name               |
+----------------------------------+--------------------+
| 6bd88b64bce14e58970ee79caffe2407 | admin              |
| fe520de27e8f4302b254fca4079ac5fe | blobStoreSvc       |
| 16042dad1da644ef80297e467dea4803 | catalogSvc         |
| 2cc454eec51344abaafd3706412a526c | customersSvc       |
| 34fd177daa9747a4ad595956b72814b7 | eventSvc           |
| 66ed9629b97d49b385147ff5a768525f | exportSvc          |
| 17c818a6f245404caf7b4d2a94876256 | fulfillmentSvc     |
| ff32adedf8a040c48aa6c6480b50553a | intadmin           |
| 7f799fc3f1c04fa18e21243e83143c16 | managementUiSvc    |
| bfc9f46507a8425db7179508dc053d28 | monitor            |
| 5206f14269034351bca13ac461c464f9 | portal             |
| 7afe5b63c02244d4899a7f99f35152ce | portalTest         |
| c2bab11b13e64886b62b3bfb8085d60c | portalUiSvc        |
| 507aad2106d848e787ea8263e24da73a | pricingSvc         |
| c286d2bea5874575b3345fc0233d6885 | reportingSvc       |
| 4672b21201fc45aeacf93d4a87494ebc | requestSvc         |
| 162d3e1c9f6848f4815d6ca037ccb2e2 | serviceInstanceSvc |
| ba9f492b6bd54ce6b71cc1bfcfd9462b | systemadmin        |
| 093a2e1ba5124a5a83656bb278fefbc7 | testadmin          |
| 7ab315d45b47453a8c46622b5a9f28d0 | testsystemadmin    |
| 69a27cff1d5249fd98f92cdd0f723181 | ticketingSvc       |
| 791e2c5eb9324e8eb40a898eab4859d8 | v2wrapperSvc       |
+----------------------------------+--------------------+
Keystone Troubleshooting
Check configuration:
cd
source env.sh
openstack configuration show
Check log file:
sudo less /var/log/keystone/keystone.log
Try to login as a user (e.g. admin) from system domain. For complete list of possible user names see the result of "openstack user list --domain system -
sort-column Name". : Replace placeholders <username>, <password> and <keystone_host> before execution
curl --request POST 'https://<keystone_host>:5000/api/idm/v3/auth/tokens' --header 'Content-Type: application
/json' --data-raw '{"auth":{"identity":{"methods":["password"],"password":{"user":{"name":"<username>","domain":
{"name":"system"},"password":"<password>"}}},"scope":{"domain":{"name":"system"}}}}' --noproxy '*' -k
4. SSP backend and frontend
Following statements are tested on CentOS Stream 8 and can be slightly different on your OS in details with your case. It is recommended to install 
backend node first, ensure it works and then install frontend node.
Step 1: Install Java
The step is required only on a backend node. You can skip this step if you plan to install only fronent services on current host.
sudo dnf install java-11-openjdk -y
After installation, check java is installed correctly:
java -version
Step 2: Install python
Run commands:
sudo dnf install python2 python2-pyyaml -y
Step 3: Install Node.js
The step is required only on frontend node. You can skip this step if you plan to install only backend services on current host.
List available versions of nodejs
sudo dnf module list nodejs
Chose the latest available version, (currently 16)
sudo dnf module enable nodejs:16 -y
Install Node.js
sudo dnf install nodejs -y
Step 4: Install nginx
Nginx is used as a default load balancer and proxy on both frontend and backend nodes.
Install nginx:
sudo dnf install nginx -y
Start nginx and enable start after reboot:
sudo systemctl enable nginx
sudo systemctl start nginx
Configure SELinux:
sudo setsebool -P httpd_can_network_connect 1
Step 5: Download Shared Services binaries
Download SSP distribution.
Unzip binaries to /opt/install. (The jar name can be different e.g. can include a version.)
sudo unzip installation-package.jar -d /opt/install
Step 6: Pick up setup.properties file
<administrationHostname> placeholder
On the Administration node, you already prepared setup.properties configuration file. Download it to current (backend/frontend) node to /opt/install. Replace
.
sudo scp ecs@<administrationHostname>:/opt/scripts/ssp/setup.properties /opt/install
Step 7: Create MySQL databases and users
The step is required only on (first) backend node. See 
backend services. The scripts uses 
mysql
/opt/scripts/database/*.sh
 CLI tool. You can
 scripts, how to create MySQL databases and users for SSP 
run the scripts from the Administration node (or any other node with mysql CLI tool installed and visibility to MySQL)
copy the scripts directly to the MySQL server and run them locally
or do the work manually using e.g. mysql CLI tool or MySQL Workbench (not recommended)
Anyway following MySQL databases and users should be created. Suppose common "ssp" prefix for all of them (of your choice) and predefined suffix per 
backend service (cannot be changed):
ssp_catalog
ssp_blobstore
ssp_customers
ssp_request
ssp_fulfill
ssp_svcinst
ssp_pricing
ssp_reporting
ssp_config
ssp_export
ssp_ticketing
ssp_event
Step 8: SSL
Ask an administrator for
If you use the prepared scripts, run following commands. Replace <prefix> placeholder for e.g. "ssp", replace <user_password> (password for all users 
being created), <root_password>(password for root user who will create databases and users) and <database_host>(IP or DNS name of your database 
server).
## install mysql client 
sudo dnf install mysql -y
cd /opt/scripts/database
./create_db_users.sh <prefix> <user_password> <root_password> <database_host>
SSL private key for the backend/frontend server (and copy it to /opt/security/server.key)
the password the private key is protected with (if protected by a password)
SSL certificate for the backend/frontend server (and copy it to /opt/security/server.crt)
SSL certificate of Certification Authority (and copy it to /opt/security/ca.crt)
... or generate these files yourself - see
SSL
chapter for details.
Moreover you need also java security keystore and truststore - see 
SSL
chapter (especially step "Create Java Keystore and Truststore")
All SSL files are usually generated on the Administration node and copy to backend/frontend node to /opt/ecs/security:
## After SSL certificate generation, files should be in the home directory of ecs user
cd
sudo mkdir -p /opt/ecs/security
sudo cp server.key server.key.nopass server.crt server_chain.crt server.keystore server.truststore ca.crt /opt
/ecs/security
Step 9: Install Shared Services
Run the installation script
cd /opt/install 
## For backend node: 
sudo su -c "python2 installer.py -i backend,backend-lb > install.log"
## or for frontend node:
# sudo su -c "python2 installer.py -i frontend,frontend-lb,doc > install.log"
## or for both frontend and backend services on the same node
# sudo su -c "python2 installer.py -i backend,frontend,frontend-lb,doc > install.log"
The installation take some time as well as booting services after installation.
Step 10: Check SSP installed
To check the installation is correct:
Check 
/opt/install/install.log
 for errors
Check status of services - backend node (see ecs-config service status first):
service ecs-config status
service ecs-blob-store status
service ecs-catalog status
service ecs-customers status
service ecs-diagnostic status
service ecs-event status
service ecs-export status
service ecs-fulfillment status
service ecs-pricing status
service ecs-reporting status
service ecs-request status
service ecs-service-instances status
service ecs-ticketing status
Check status of services - frontend node:
service ecs-management-ui status
service ecs-portal-ui status
service ecs-api-doc status
Check logs of services for errors. Logs are located in /var/log/ecs/. Note that some errors may occure when some service tries to find a queue in 
RabbitMQ that will be created by other service with longer boot time, so not all exceptions are real errors.
When both backend and frontend nodes are installed, wait e.g. 5 minutes for services to boot, open Administration UI in browser https://<fron
, login as systemadmin
tend_hostname>/ui/management/login/system
try to see Catalog Items, Service Designs, Request, Service Instances and Diagnostics (sometime diagnostics may show obsolete info, 
try to refresh).
To check API documentation, open 
https://
<frontend_hostname>
HA Installation
/api-doc/swagger-ui/index.html
 in your browser.
High Availability (HA) installation process generally consist of 2 or more single-node installations (described before) with additional steps to bind nodes to a 
cluster.
RabbitMQ - HA
Install RabbitMQ cluster according to RabbitMQ clustering documentation ( ). Following steps are tested on https://www.rabbitmq.com/clustering.html
CentOS Stream 8 nodes, but they can be a bit different e.g. due to network infrastructure.
Suppose an installation of 2 RabbitMQ servers of 2 standalone VM/servers called node1 and node2 (please replace with real hostnames in your 
environment). Each node is by default in a standalone cluster (consisting of one node) after installation. This chapter describes how to reuse the default 
cluster of the node1 and add the node2 to that cluster. Despite it is generally recommended to use odd number of nodes in RabbitMQ clusters due to 
several features like quorum queues, such features are not used by SSP services and 2-nodes cluster is suitable. You can add another nodes to the 
cluster in similar way, if needed.
Step 1: Hostname resolution
Hostnames (short or fully-qualified domain name, preferably both) of all cluster members must be resolvable from all cluster nodes. Hostname resolution 
method depends on your infrastrucure, e.g. you can use DNS records or local files (/etc/hosts). You can ensure the nodes are resolvable from other nodes 
e.g. using ping command on node1:
Node1
sudo ping <node2>
sudo ping <node2.domain>
... and on node2:
Node2
sudo ping <node1>
sudo ping <node1.domain>
Correct any problems in hostname resolution before proceeding.
Step 2: Install nodes
Instance node1, see Chapter  above for details. RabbitMQ
Instance node2, see Chapter  above for details. In case of node2 (and further) you can skip data preparation including users and vhosts RabbitMQ
(Step 4 and 7), because whole node2 data must be removed before attaching a cluster. Node2 data will be synced from the cluster afterward.
Step 3: Check RabbitMQ node names
To get know the RabbitMQ node name of node1 run following command on node1:
Node1
sudo rabbitmqctl status
See an example of the output:
Status of node rabbit@ssprabbit ...
Runtime
OS PID: 84017
OS: Linux
Uptime (seconds): 15949
Is under maintenance?: false
RabbitMQ version: 3.9.13
Node name: rabbit@ssprabbit
Erlang configuration: Erlang/OTP 24 [erts-12.2.1] [source] [64-bit] [smp:2:2] 
[d                                                                                                              
s:2:2:10] [async-threads:1] [jit]
Erlang processes: 574 used, 1048576 limit
Scheduler run queue: 1
Cluster heartbeat timeout (net_ticktime): 60
...
The node name should be in form "rabbit@<node1_hostname>", where <node1_hostname> is resolvable on node2 (e.g. ping <node1_hostname> on 
node2).
To get know the RabbitMQ node name of node2 run following command on node2:
Node2
sudo rabbitmqctl status
The node name should be in for "rabbit@<node2_hostname>", where the node2_hostname is resolvable on node1 (e.g. ping <node2_hostname> on 
node1).
Step 4: Open ports
Open ports for inter-node communication on both nodes:
Node1 + Node2
sudo firewall-cmd --add-port=4369/tcp --permanent
sudo firewall-cmd --add-port=25672/tcp --permanent
sudo firewall-cmd --reload
Step 5: Configure common Erlang cookie
All cluster nodes must use the same Erlang cookie for authentication. Use the node1 Erlang cookie and copy it to node2 (Replace <node1_hostname> 
), change owner of the erlang cookie and restart the RabbitMQ: placeholder
Node2
sudo rm /var/lib/rabbitmq/.erlang.cookie
sudo scp root@<node1_hostname>:/var/lib/rabbitmq/.erlang.cookie /var/lib/rabbitmq/.erlang.cookie
sudo chown rabbitmq:rabbitmq /var/lib/rabbitmq/.erlang.cookie
sudo systemctl restart rabbitmq-server
Ensure the RabbitMQ (node2) is running wihout problems:
Node2
sudo rabbitmqctl status
Step 6: Add node2 to cluster
On the node2, stop the RabbitMQ application, leaving the runtime (Erlang VM) running:
Node2
sudo rabbitmqctl stop_app
Reset the RabbitMQ node2 to initial state (removes the node from default cluster, removes all data such as users, vhosts and messages):
Node2
sudo rabbitmqctl reset
Join node2 to the existing cluster of node1 (use node1 as seed node - ): replace <node1_hostname> placeholder
Node2
sudo rabbitmqctl join_cluster rabbit@<node1_hostname>
Start the RabbitMQ node again:
Node2
sudo rabbitmqctl start_app
Step 7: Check cluster
On both nodes, run:
sudo rabbitmqctl cluster_status
Regardlest of the node where you are, there should be both nodes mentiond in the output:
Output
Running Nodes
rabbit@<node1_hostname>
rabbit@<node2_hostname>
Check that vhosts and users configured on node1 are also available on the node2. On both nodes, run:
sudo rabbitmqctl list_vhosts
sudo rabbitmqctl list_users
Appendix 1: SSL
If you decided to generate SSL files yourself and use you own root Certification Authority (with self-signed certificate), you can proceed and use prepared 
scripts. It is assumed to generate all needed files on the administration node and distribute generated files only to the nodes the key/certificate is intended 
for. Private key files should be kept safe, especially root CA private key should not leave the administration node. Steps 3 should be done 4 times: for 
frontend node, backend node, rabbitmq node and keystone node. Please backup generated files, because next run of the script will rewrite previously 
generated files.
Step 1: Generate CA private key and certificate
Note that you need to generate CA private key and certificate only once and then you can reuse them everytime CA files are needed to sign certificates for 
dedicated nodes.
You can run prepared gen_ca_cert.sh script. . Replace <ca_password> placeholder
Generate CA private key and certificate using script
cd /opt/scripts/ssl/ca
sudo su -c "./gen_ca_cert.sh <ca_password>"
The script generates
ca.key - private key, keep it safe
ca.crt - certificate, distribute it to other nodes if needed
Step 2: Install java
Java is needed to generate Java Keystore and Truststore for backend services.
sudo dnf install java-11-openjdk -y
After installation, check java is installed correctly:
java -version
Step 3: Generate server private key and certificate
Generate SSL private key and certificate for a particular server. You will do this separately for each node.
You can run gen_cert.sh (use gen_cert_rsa.sh in case of RabbitMQ server). Replace <host_ip>, <key_password> and <ca_password> placeholders.
cd /opt/scripts/ssl
sudo su -c "./gen_cert.sh <host_ip> IP:<host_ip> <key_password> <ca_password>"
## Alternatively use domain_name
#sudo su -c "./gen_cert.sh <domain_name> DNS:<domain_name> <key_password> <ca_password>"
The script generates
server.key - private key protected by password
server.key.nopass - private key without protection
server.crt - server centificate
server.keystore - Java key store containing private key
server.truststore - Java trust store with CA certificate
Step 4: Create Java Keystore and Truststore
Java Keystore and Truststore are needed only for Shared Services Backend node. If you used gen_cert.sh script, the keystore and the truststore are 
already generated and you can skip this step. 
Following commands are useful in case you obtained server.key, service.crt and ca.crt from administrator and you need to create Java Keystore and 
Truststore manually.
Create certificate chain:
cd /opt/scripts/ssl
sudo cat server.crt ca/ca.crt > server_chain.crt
Generate keystore. Replace <password> placeholder.
sudo openssl pkcs12 -export -inkey server.key -in server_chain.crt -out server.pfx -name server -passin "pass:
<password>" -passout "pass:<password>"
sudo keytool -importkeystore -srcstoretype PKCS12 -alias server -srckeystore server.pfx -srcstorepass 
"<password>" -srckeypass "<password>" -destkeystore server.keystore -deststorepass "<password>" -destkeypass 
"<password>"
Generate truststore. Replace <password> placeholder.
cp /etc/pki/java/cacerts server.truststore
keytool -storepasswd -keystore server.truststore -storepass changeit -new "<password>"
keytool -importcert -file ca/ca.crt -keystore server.truststore -alias 'CPI CA' -storepass "<password>" 
noprompt
Step 5: Copy files to target node
Copy files to target node. Replace <hostname> placeholder.
sudo scp server.key server.key.nopass server.crt server_chain.crt ca/ca.crt ecs@<hostname>:/home/ecs
In case of backend service node, copy also keystore and truststore:
sudo scp server.truststore server.keystore ecs@<hostname>:/home/ecs
Appendix 2: Password encryption
Using plain-text passwords in configuration files is generally not a good idea - It is recommended to encrypt passwords in SSP configuration files. SSP 
uses a password-based-encryption algorithm like 
PBEWITHSHA256AND256BITAES-CBC-BC
. The algorithm needs a shared secret (known to the 
administrator and to the SSP services) to deterministically generate key for the encryption/decryption algorithm. Configuration files still needs to be kept 
safe, because the shared secret is also mentioned in the configuration. An attacker could decrypt your password knowing the encrypted password, the 
algorithm and the shared secret from the configuration.
Step 1: Install Jasypt and BouncyCastle
Download jasypt and unzip it to /opt/jasypt on the administration node:
cd /tmp
curl -sOL https://github.com/jasypt/jasypt/releases/download/jasypt-1.9.3/jasypt-1.9.3-dist.zip
sudo unzip jasypt-1.9.3-dist.zip -d /opt/jasypt
Download Bouncy Castle provider and copy it to jasypt lib directory:
curl -sOL https://www.bouncycastle.org/download/bcprov-jdk15on-170.jar
sudo cp bcprov-jdk15on-170.jar /opt/jasypt/jasypt-1.9.3/lib/
 Check where is your java installed (the directory can vary - 
replace the <path_to_jdk> placeholder
sudo vi <path_to_jdk>/conf/security/java.security
Append following line after the list of security providers (
use the first greater provider index
security.provider.13=org.bouncycastle.jce.provider.BouncyCastleProvider
Make jasypt script files executable:
cd /opt/jasypt/jasypt-1.9.3/bin
sudo chmod u+x *.sh
Step 2: Encrypt a password
The configuration file
Encrypt a password - 
 /opt/scripts/ssp/quickSetup.properties
) and edit the java.security file:
):
 contains parameters of encryption:
propertiesEncryptionAlgorithm - declares encryption autgorithm, the recommended value is  PBEWITHSHA256AND256BITAES-CBC-BC
propertiesEncryptionKey - shared secret for the algorithm, set it once and keep it stable (otherwise SSP service will not be able to decrypt 
passwords and sensitive data in database).
replace <value> (your password) and <shared_secret>
 :
cd /opt/jasypt/jasypt-1.9.3/bin
sudo ./encrypt.sh input=<value> password=<shared_secret> algorithm=PBEWITHSHA256AND256BITAES-CBC-BC
Note that the encrypted password must be used in the configuration file in form ENC(<encrypted_password>)
Do the encryption for all password fields in the 
/opt/scripts/ssp/quickSetup.properties
 file:
serviceAccountPassword=ENC(<encrypted_password>)
...
javaSecurityPasswordEncoded=ENC(<encrypted_password>)
...
dbUserPassword=ENC(<encrypted_password>)
...
rabbitmqUserPassword=ENC(<encrypted_password>)
...
idmUserPassword=ENC(<encrypted_password>)
Appendix 3: Shared Service upgrade and re-installation
You can upgrade to new version of Shared Services (or re-install  the same binaries) without lost of data in your MySQL database and KeyStone. The 
upgrade process needs only to replace binaries. Possible incompatible data changes between versions of Shared Services will be handled during first boot 
of new binaries.
There are two ways of upgrade:
Complete replacement - Removes all service binaries and replaces the them completely with newer binaries
Partial replacement - Replaces only services that have been changed from the last installation.
Complete replacement
In case of upgrade, download new installation package (e.g. to the /tmp directory) before any further steps.
Backup setup.properties files:
sudo cp /opt/install/setup.properties /opt/scripts/ssp/setup.properties.backup
Shutdown services, delete binaries of installed services and logs using cleanup.sh script:
cd /opt/scripts/ssp
sudo ./cleanup.sh
(Optional) In case of upgrade, go to /tmp (or wherever you downloaded the binaries) remove old binaries from /opt/install and unpack new binaries to /opt
 ( with the real package name including version). In case of re-installation the binaries are already in /install replace <installation-package.jar> /opt
 /install
# cd /tmp
# sudo rm -r /opt/install
# sudo unzip <installation-package.jar> -d /opt/install
Compare /opt/scripts/ssp/setup.properties.backup and /opt/install/setup.properties:
if a new property is introduced in /opt/install/setup.properties, download new installation scripts, fill quickSetup.properties again and generate new 
setup.properties - see Step 3: Edit installation property file
else copy setup.properties back to the install directory:
sudo cp /opt/scripts/ssp/setup.properties.backup /opt/install/setup.properties
Copy generated security files (does not matter if you prepared them manually or via gen_cert.sh script) to /opt/ecs/security. If you lost security files, see 
above how to generate them again.
sudo mkdir -p /opt/ecs/security
sudo cp server.key server.crt server_chain.crt server.keystore server.truststore ca/ca.crt /opt/ecs/security
(Sometimes required) In case of new service requires a standalone database and database user, run create_db_user.sh again or create the database and 
user manually - see Step 7: Create MySQL databases and users
Run the installation again. : Replace <part_list> placeholder
to reinstall backend: backend,backend-lb
to reinstall frontend: frontend,frontend-lb,doc
to reinstall backend and frontend on the same server: backend,frontend,frontend-lb,doc
cd /opt/install
sudo su -c "python2 installer.py -i <part_list> > install.log"
## Examples:
# sudo su -c "python2 installer.py -i backend,backend-lb > install.log"
# sudo su -c "python2 installer.py -i frontend,frontend-lb,doc > install.log"
# sudo su -c "python2 installer.py -i backend,frontend,frontend-lb,doc > install.log"
Partial replacement
Download new installation package (e.g. to the /tmp directory).
Backup setup.properties files:
sudo cp /opt/install/setup.properties /opt/scripts/ssp/setup.properties.backup
Delete /opt/install directory with obsolete binaries and unpack new bineries there (
version).
replace <installation-package.jar>
 with the real package name including 
cd /tmp
sudo rm -r /opt/install
sudo unzip <installation-package.jar> -d /opt/install
Compare /opt/scripts/ssp/setup.properties.backup and /opt/install/setup.properties: 
if a new property is introduced in /opt/install/setup.properties, download new installation scripts, fill quickSetup.properties again and generate new 
setup.properties - see Step 3: Edit installation property file
else copy setup.properties back to the install directory:
sudo cp /opt/scripts/ssp/setup.properties.backup /opt/install/setup.properties
(Sometimes required) In case of new service requires a standalone database and database user, run create_db_user.sh again or create the database and 
user manually - see Step 7: Create MySQL databases and users
Run the update script. Replace <part_list> placeholder. Use updater.py instead of installer.py
to update backend: backend,backend-lb
to update frontend: frontend,frontend-lb,doc
to update backend and frontend on the same server: backend,frontend,frontend-lb,doc
cd /opt/install
sudo su -c "python2 updater.py -i <part_list> > install.log"
## Examples:
# sudo su -c "python2 updater.py -i backend,backend-lb > install.log"
# sudo su -c "python2 updater.py -i frontend,frontend-lb,doc > install.log"
# sudo su -c "python2 updater.py -i backend,frontend,frontend-lb,doc > install.log"