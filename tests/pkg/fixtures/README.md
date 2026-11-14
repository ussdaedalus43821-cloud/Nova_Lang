# Test fixtures

`localhost.pem` and `localhost.key` are a **test-only** self-signed certificate for `localhost` and `127.0.0.1` (valid for 100 years)
and its private key. `test_registry.py` starts a local HTTPS server with them and tells `nova-pkg` to trust the certificate through
`NOVA_PKG_CA_FILE`; nothing else uses them. The key protects nothing: it is public in the repository, so never trust this certificate
anywhere.
