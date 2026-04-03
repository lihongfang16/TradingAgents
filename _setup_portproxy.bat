# Run as admin: netsh interface portproxy add v4tov4 listenport=5432 listenaddress=127.0.0.1 connectport=5432 connectaddress=172.20.153.76
# Check: netsh interface portproxy show all
# Remove: netsh interface portproxy delete v4tov4 listenport=5432 listenaddress=127.0.0.1
