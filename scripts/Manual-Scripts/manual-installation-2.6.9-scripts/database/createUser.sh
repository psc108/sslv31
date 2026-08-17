#!/bin/bash
if [ "$#" -ne 5 ]; then
  echo "Creates MySQL database and user for single SSP backend service." >&2
  echo "Do not use this script directly - use create_db_users.sh to create all databases and users at once." >&2
  echo "Usage: $0 <user_and_database_name> <user_password> <database_host> <admin_user> <admin_password>" >&2
  exit 1
fi

set -x

mysql -h "$3" -u "$4" "-p$5" "mysql" -Bse \
"
CREATE DATABASE $1 CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER $1 IDENTIFIED BY '$2';
GRANT ALL ON $1.* to $1;
"