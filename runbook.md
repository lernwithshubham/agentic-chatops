# Nginx Error SOP
If error contains 'worker_connections are not enough':
Root Cause: Sudden traffic spike locked the worker threads.
Approved Remediation: Run 'docker restart nginx-web' to instantly clear the thread pool lock.