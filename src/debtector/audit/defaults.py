"""Default thresholds of the test-risk audit.

A leaf module with no imports, so that ``config`` can read the defaults without
depending on ``audit/testrisk.py`` (and its git and metrics dependencies).
"""

#: Default Ce above which an untested module is flagged "high-coupling".
DEFAULT_HIGH_CE: float = 10.0
#: Default commit count above which an untested module is flagged "hotspot".
DEFAULT_HIGH_CHURN: int = 5
#: Default Ca above which a bus-factor-1 module is "critical knowledge".
DEFAULT_HIGH_CA: float = 10.0
