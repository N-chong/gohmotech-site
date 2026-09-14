"""Root-only creation of a new, dedicated MariaDB beta database and user."""

import os
import re

import pymysql
from dotenv import dotenv_values

if os.geteuid() != 0:
    raise SystemExit('Run as root for MariaDB local socket authentication.')
config = dotenv_values('/home/gohmotech/.config/gohmotech/beta.env')
database = config['BETA_DB_NAME']
username = config['BETA_DB_USER']
if database != 'gohmotech_beta' or username != 'gohmotech_beta':
    raise SystemExit('Only the dedicated gohmotech_beta database/user may be created.')
if not re.fullmatch(r'[0-9a-f]{64}', config['BETA_DB_PASSWORD']):
    raise SystemExit('Expected a generated beta database password.')

connection = pymysql.connect(user='root', unix_socket='/run/mysqld/mysqld.sock', autocommit=True)
try:
    with connection.cursor() as cursor:
        cursor.execute('SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s', (database,))
        if cursor.fetchone():
            raise SystemExit('Beta database already exists; refusing to overwrite it.')
        cursor.execute('SELECT User FROM mysql.user WHERE User=%s', (username,))
        if cursor.fetchone():
            raise SystemExit('Beta database user already exists; refusing to alter its credentials.')
        cursor.execute('CREATE DATABASE `gohmotech_beta` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
        cursor.execute("CREATE USER 'gohmotech_beta'@'127.0.0.1' IDENTIFIED BY %s", (config['BETA_DB_PASSWORD'],))
        cursor.execute("GRANT ALL PRIVILEGES ON `gohmotech_beta`.* TO 'gohmotech_beta'@'127.0.0.1'")
except pymysql.MySQLError as exc:
    raise SystemExit(f'MariaDB provisioning failed (error {exc.args[0]}). Credentials omitted.') from None
finally:
    connection.close()
print('Created isolated beta database and database-scoped account. Existing farm data unchanged.')
