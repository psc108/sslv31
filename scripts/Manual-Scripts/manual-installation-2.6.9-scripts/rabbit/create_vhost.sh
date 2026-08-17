#!/bin/bash

if [ "$#" -ne 1 ]; then
  echo "Creates RabbitMQ vhost and adds permission to users" >&2
  echo "Usage: $0 vhost" >&2
  echo "  e.g.: $0 /ssp" >&2
  exit 1
fi

rabbitmqctl add_vhost $1 && true

rabbitmqctl set_permissions -p $1 blobstore ".*" ".*" ".*"
rabbitmqctl set_permissions -p $1 catalog ".*" ".*" ".*"
rabbitmqctl set_permissions -p $1 customer ".*" ".*" ".*"
rabbitmqctl set_permissions -p $1 event ".*" ".*" ".*"
rabbitmqctl set_permissions -p $1 fulfillment ".*" ".*" ".*"
rabbitmqctl set_permissions -p $1 pricing ".*" ".*" ".*"
rabbitmqctl set_permissions -p $1 reporting ".*" ".*" ".*"
rabbitmqctl set_permissions -p $1 request ".*" ".*" ".*"
rabbitmqctl set_permissions -p $1 svcinst ".*" ".*" ".*"
rabbitmqctl set_permissions -p $1 config ".*" ".*" ".*"
rabbitmqctl set_permissions -p $1 export ".*" ".*" ".*"
rabbitmqctl set_permissions -p $1 ticketing ".*" ".*" ".*"
rabbitmqctl set_permissions -p $1 extevt ".*" ".*" ".*"