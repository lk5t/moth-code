"""MOTH Server — owner-operated services for MOTH Code.

Components (separate modules, one deployable app or several processes):

* ``routes/auth``      accounts, sessions, email verification, recovery, profiles
* ``routes/billing``   plans, subscriptions, usage metering, payment webhooks
* ``routes/referrals`` referral codes, attribution and rewards
* ``routes/training``  worker enrollment, job scheduling, verified contributions
* ``routes/models``    signed model-release manifests and downloads
* ``routes/admin``     owner dashboard API
* ``routes/inference`` metered MOTH Cloud inference (disabled until GPUs exist)

MOTH's intelligence is always MOTH's own model; the server never calls third-party AI.
"""

__version__ = "0.5.1"
