import os
import sys
import toml
sys.path.insert(0, '.')
secrets = toml.load('.streamlit/secrets.toml')
os.environ['SQL_CONNECTION_STRING'] = secrets['SQL_CONNECTION_STRING']
import db

# Queries to fetch data for the year 2026
queries = {
    'pistereftrainingsince': "SELECT * FROM pistereftrainingsince WHERE age = 2026",
    'pistereftrainingtime': "SELECT * FROM pistereftrainingtime WHERE age = 2026"
}

# Execute each query and print the results
for table, query in queries.items():
    result = db.query(query)
    print(f"Data in {table} for 2026:")
    for row in result:
        print(row)