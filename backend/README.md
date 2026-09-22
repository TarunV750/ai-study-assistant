# Backend

Python Lambda handlers live in `functions`, while reusable domain and AWS
integration code lives in `shared`. Unit tests live in `tests` and will mock
AWS boundaries where appropriate.

The packages are empty in Phase 1 by design. Core behavior will be added and
tested incrementally rather than represented by non-functional placeholders.
