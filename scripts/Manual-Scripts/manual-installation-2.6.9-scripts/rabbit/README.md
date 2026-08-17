# RabbitMQ Scripts

## create_users.sh

Creates users for all backend services. If you plan to run multiple independent SSP instances with single shared RabbitMQ server, 
it is needed to run create_users.sh script only once.

Usage
```
./create_users.sh [password]
```
Parameters:
* password - the password is common to all created users for simplicity.


## create_vhost.sh

Creates RabbitMQ Virtual Host (vhost) and adds permissions to the users for the vhost.
If you plan to run multiple independent SSP instances with single shared RabbitMQ server, 
it is needed to run create_vhost.sh script for each SSP instance with unique `vhost` name.

Usage
```
./create_vhost.sh [vhost]
```
e.g.
```
./create_vhost.sh /ssp
```
