"""Web API layer: a read-only + trigger wrapper around Coordinator and the
runs/ artifact directory. No research logic lives here - it only reads what
Coordinator already produced and serves it over HTTP."""
