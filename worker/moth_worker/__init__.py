"""MOTH Worker — trains MOTH model rounds assigned by the MOTH training coordinator.

The worker only trains on data shards supplied by the coordinator (checksum-verified) and
uploads weight updates. It never reads other files on the machine and is not an AI assistant.
"""

__version__ = "0.5.7"
