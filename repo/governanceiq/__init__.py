"""GovernanceIQ Django project package."""
import pymysql

# Use PyMySQL as the MySQL driver for Django so we don't depend on libmysqlclient.
pymysql.install_as_MySQLdb()
