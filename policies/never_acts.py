"""Never-acts baseline: read the first message and leave without a single action.

It is here because the result should be on the sheet, not only in a footnote: the
episode is truncated, truncation counts as an empty submission, and on clean books
that is a perfect score.
"""

from __future__ import annotations

import sys

if __name__ == "__main__":
    sys.stdin.readline()
