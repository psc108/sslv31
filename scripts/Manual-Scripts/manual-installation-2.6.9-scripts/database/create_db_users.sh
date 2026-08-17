#!/bin/bash
if [ "$#" -ne 5 ] && [ "$#" -ne 6 ]; then
  echo "Creates MySQL databases and users for all SSP backend services." >&2
  echo "If \"dropIfExists\" is specified as fifth parameter, databases and users are dropped before creation." >&2
  echo "Usage: $0 <user_and_database_prefix> <user_password> <database_host> <admin_user> <admin_password> [dropIfExists]" >&2
  exit 1
fi

set -x

if [ "$6" = "dropIfExists" ]; then
  # Try to drop previously created databases and users if exist
  ./dropUser.sh $1_catalog $3 $4 $5
  ./dropUser.sh $1_blobstore $3 $4 $5
  ./dropUser.sh $1_customers $3 $4 $5
  ./dropUser.sh $1_request $3 $4 $5
  ./dropUser.sh $1_fulfill $3 $4 $5
  ./dropUser.sh $1_svcinst $3 $4 $5
  ./dropUser.sh $1_pricing $3 $4 $5
  ./dropUser.sh $1_reporting $3 $4 $5
  ./dropUser.sh $1_config $3 $4 $5
  ./dropUser.sh $1_export $3 $4 $5
  ./dropUser.sh $1_ticketing $3 $4 $5
  ./dropUser.sh $1_event $3 $4 $5
  ./dropUser.sh $1_extevt $3 $4 $5
fi

# Create new databases and users
./createUser.sh $1_catalog $2 $3 $4 $5
./createUser.sh $1_blobstore $2 $3 $4 $5
./createUser.sh $1_customers $2 $3 $4 $5
./createUser.sh $1_request $2 $3 $4 $5
./createUser.sh $1_fulfill $2 $3 $4 $5
./createUser.sh $1_svcinst $2 $3 $4 $5
./createUser.sh $1_pricing $2 $3 $4 $5
./createUser.sh $1_reporting $2 $3 $4 $5
./createUser.sh $1_config $2 $3 $4 $5
./createUser.sh $1_export $2 $3 $4 $5
./createUser.sh $1_ticketing $2 $3 $4 $5
./createUser.sh $1_event $2 $3 $4 $5
./createUser.sh $1_extevt $2 $3 $4 $5
