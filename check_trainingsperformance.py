import os
import sys
import toml
sys.path.insert(0, '.')
secrets = toml.load('.streamlit/secrets.toml')
os.environ['SQL_CONNECTION_STRING'] = secrets['SQL_CONNECTION_STRING']
import db

# Query to fetch data from trainingsperformance for 2026
query = "SELECT * FROM trainingsperformance WHERE PisteYear = 2026"

# Execute the query and print the results
result = db.query(query)
print("Data in trainingsperformance for 2026:")
for row in result:
    print(row)