# SSP Scripts
Scripts for installation of SSP frontend and backend services. See SSP installation guide for details.

## Installation
It is expected, that you have already prepared
* RabbitMQ server (or cluster), created vhost, users and their permissions - see ../rabbit/README.md
* MySQL users and databases for each backend service - see ../database/README.md
* OpenStack KeyStone identity management server, roles and system domain users and roles assignment them - see ../idm/README.md

Then please follow these steps:
* Edit `quickSetup.properties`: The file contains a subset of installer properties that are intended to be customizable. 
  Please check especially hostnames (SSP services, MySQL, Rabbit, KeyStone), ports, passwords and proxyOptions.
* Run `buildProperties.py` to generate `setup.properties` based on `quickSetup.properties` and predefined `setup.properties.template`
* Copy `setup.properties` to `/opt/install` 
* Finally, run the installation using `install.py`

## Un-installation
Use `cleanup.sh` to stop all running SSP services, remove SSP service binaries, logs and installation files.