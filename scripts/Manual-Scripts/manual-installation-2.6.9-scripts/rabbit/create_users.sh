#!/bin/bash

if [ "$#" -ne 1 ]; then
  echo "Creates RabbitMQ users for all backend services." >&2
  echo "Usage: $0 password" >&2
  exit 1
fi

rabbitmqctl add_user blobstore $1
rabbitmqctl add_user catalog $1
rabbitmqctl add_user customer $1
rabbitmqctl add_user event $1
rabbitmqctl add_user fulfillment $1
rabbitmqctl add_user pricing $1
rabbitmqctl add_user reporting $1
rabbitmqctl add_user request $1
rabbitmqctl add_user svcinst $1
rabbitmqctl add_user config $1
rabbitmqctl add_user export $1
rabbitmqctl add_user ticketing $1
rabbitmqctl add_user extevt $1