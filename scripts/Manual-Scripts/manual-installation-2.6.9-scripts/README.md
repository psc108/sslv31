# Manual Installation Scripts

Set of tools and scripts that helps to install Shared Service Portal components. 
See SSP Installation Guide for details
(the original is located at https://confluence.dxc.com/display/VSA/On+Premise+Installation+Guide).

## Structure
Scripts are grouped to directories by themes. 
* `database` - scripts to create and drop MySQL users for SSP backend services
* `idm` - scripts to initialize OpenStack KeyStone: roles and system domain users
* `rabbit` - scripts to initialize RabbitMQ: create users for SSP backend services and assign permissions
* `ssl` - scripts to generate private key and certificate for your server(s), used for RabbitMQ, KeyStone and SSP servers.
   * `ssl/ca` - scripts to generate private key and certificate of you local Certification Authority (CA)
* `ssp` - installation of SSP frontend and backend services




