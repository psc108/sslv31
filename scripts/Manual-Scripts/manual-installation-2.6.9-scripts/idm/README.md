# KeyStone Patch and Scripts
OpenStack KeyStone is an identity management system for SSP. 

Note the only supported KeyStone version is "Antelope".

* patch/common.py - Patch for Keystone - applicable only for "Antelope" release/version. To be placed in site-packages/keystone/token/providers/common.py
* policy.json - Keystone policy file to be replaced in /etc/keystone/policy.json 
* create_roles.sh - Creates low level and composed roles for SSP in KeyStone.
* create_system_domain.sh - Creates system users (for administrators) and service users (for inter service communication) and assign roles to them.


