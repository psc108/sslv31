#!/bin/bash
if [ "$#" -ne 4 ]; then
  echo "Drops MySQL database and user for single SSP backend service." >&2
  echo "Do not use this script directly - use create_db_users.sh to delete and create all databases and users at once." >&2
  echo "Usage: $0 <user_and_database_name> <database_host> <admin_user> <admin_password>" >&2
  exit 1
fi

set -x

mysql -h "$2" -u "$3" "-p$4" "mysql" -Bse \
"
DROP DATABASE $1;
DROP USER $1;
"