"""The pure core of the engine: definitions, validation, routing, expressions, schedules.

Nothing in this package performs I/O, so every rule about how a workflow runs is covered
by fast unit tests. Workers and services move state between Postgres and these functions.
"""
