"""Sovereign Ledger bank importers — pure parsing + identity layer.

Nothing under ``importers/`` posts anything to the ledger (HR-5: drafts
only).  The parsing and canonicalization functions here are pure: they
take bytes/strings and produce ``BankLine`` draft values.  The caller
(an app route in Step 7) persists batches and lines to the DB.

Package layout:

* :mod:`importers.base`   — ``BankImporter`` protocol, ``BankLine`` type
* :mod:`importers.hash`   — canonicalization + batch/line hashing (D-9)
* :mod:`importers.profiles` — version-stamped per-account profiles (CK-2)
* :mod:`importers.csv_generic` — CSV parser driven by profile column map
* :mod:`importers.ofx`    — QFX/OFX parser via ofxtools 1.1.1, FITID keying
"""