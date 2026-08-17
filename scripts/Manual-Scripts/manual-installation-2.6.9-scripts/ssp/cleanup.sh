#!/bin/bash

echo "Stop all running SSP services, remove SSP service binaries, logs and installation files."
read -p "Do you want to proceed [y/N]? " answer
if [ "$answer" != "y" ] ;then
    echo "No cleanup."
    exit 1
fi

    systemctl stop ecs-catalog || true
    systemctl stop ecs-fulfillment || true
    systemctl stop ecs-blob-store || true
    systemctl stop ecs-customers || true
    systemctl stop ecs-management-ui || true
    systemctl stop ecs-portal-ui || true
    systemctl stop ecs-event || true
    systemctl stop ecs-request || true
    systemctl stop ecs-service-instances || true
    systemctl stop ecs-pricing || true
    systemctl stop ecs-reporting || true
    systemctl stop ecs-ticketing || true
    systemctl stop ecs-config || true
    systemctl stop ecs-api-doc || true
    systemctl stop ecs-diagnostic || true
    systemctl stop ecs-export || true
    systemctl stop ecs-external-events || true
rm -rf /opt/ecs
rm -rf /var/log/ecs
rm -rf /opt/install/work
echo "SSP cleaned."