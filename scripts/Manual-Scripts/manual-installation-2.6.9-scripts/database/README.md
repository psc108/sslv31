# MySQL Scripts

## create_db_users.sh

Creates databases and users for all backend services. Use the script 
* directly on MySQL server 
* or from other server with network visibility to MySQL server, with `mysql` client installed. 
  Applicable if admin (root) user can connect from remote host. 

Consult these options with your database administrator.

Usage
```
./create_db_users.sh [user_and_database_prefix] [user_password] [database_host] [admin_user] [admin_password] 
```

To create keystone databe it could be used as following
```
./createUser.sh keystone [user_password] [database_host] [admin_user] [admin_password] 
```

Parameters:
* [user_and_database_prefix] - common prefix for all user and database names. For example if you specify prefix `ssp`, following databases and users are created: 
  * ssp_catalog
  * ssp_blobstore
  * ssp_customers
  * ssp_request
  * ssp_fulfill
  * ssp_svcinst
  * ssp_pricing
  * ssp_reporting
  * ssp_config
  * ssp_export
  * ssp_ticketing
  * ssp_event
  * ssp_extevt
* [user_password] - all created users will have the same password for simplicity
* [admin_password] - admin/root password - the account must be able to create databases and users
* [database_host] - hostname of the MySQL server

## Other scripts
* createUser.sh - Do not use it directly.
* dropUser.sh - Do not use it directly.