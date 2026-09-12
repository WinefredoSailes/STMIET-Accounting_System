"""Shared domain constants — single source of truth for cross-app values.

Keeping values here (instead of literal integers/labels sprinkled across apps)
lets a concept change once and propagate to every model form that uses it.
"""

# Cost center / ref: the display-level charge label carried on payment
# documents and their lines (e.g. "OS — offsite", "GEN-FUEL"). One width
# everywhere (RFP lines, PCF header) so the same value round-trips through
# forms, prints, and the JE line reference field intact. Payroll-feed and
# document-sequence cost centers are short identifier codes, NOT this concept.
COST_CENTER_MAX_LENGTH = 64