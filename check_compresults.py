import os
import sys
import toml
sys.path.insert(0, '.')
secrets = toml.load('.streamlit/secrets.toml')
os.environ['SQL_CONNECTION_STRING'] = secrets['SQL_CONNECTION_STRING']
import db

# Query to count the number of rows in the compresults table
query = "SELECT COUNT(*) AS count FROM compresults"

# Execute the query and fetch the result
result = db.query(query)

# Print the count of rows in the compresults table
print(f"Number of rows in compresults: {result[0]['count']}")

# Queries to count the number of rows in athletes and pisteresults tables
queries = {
    'compresults': "SELECT COUNT(*) AS count FROM compresults",
    'athletes': "SELECT COUNT(*) AS count FROM athletes",
    'pisteresults': "SELECT COUNT(*) AS count FROM pisteresults"
}

# Execute each query and print the results
for table, query in queries.items():
    result = db.query(query)
    print(f"Number of rows in {table}: {result[0]['count']}")