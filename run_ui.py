import os
import sys
import subprocess

# Set environment variables
os.environ['API_URL'] = 'http://localhost:8005'
os.environ['DATABASE_URL'] = 'postgresql://trading:trading123@172.16.1.8:5432/trading_db'

# Run Streamlit
sys.path.insert(0, r'D:\1.MyProjects\Other\tradingagents-a-share')

result = subprocess.run([
    sys.executable, '-m', 'streamlit', 'run', 
    r'D:\1.MyProjects\Other\tradingagents-a-share\web\app.py',
    '--server.port', '8501',
    '--server.address', '0.0.0.0'
], cwd=r'D:\1.MyProjects\Other\tradingagents-a-share')
