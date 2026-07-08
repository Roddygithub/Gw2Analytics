"""v0.9.0 backend: background worker module.

Houses the webhook delivery dispatcher and (in v0.9.1+) the
retry / DLQ scheduler. Each worker takes a SQLAlchemy
``session_factory`` callable as a positional arg to keep the
request-session anti-pattern out of the BG-task surface.
"""
