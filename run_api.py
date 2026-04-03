import os
import sys

# Set environment variables
os.environ['DATABASE_URL'] = 'postgresql://trading:trading123@172.16.1.8:5432/trading_db'
os.environ['API_URL'] = 'http://localhost:8005'

# Run the API server
sys.path.insert(0, r'D:\1.MyProjects\Other\tradingagents-a-share')

from webapi.server import app
import uvicorn

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8005)
