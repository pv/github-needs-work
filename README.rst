=================
github-needs-work
=================

::

      usage: github_needs_work.py

      Print pull requests in Github which have needs-work label despite
      having updated commits. Creates a cache file ``gh_cache.json`` in
      the current directory.

      optional arguments:
      -h, --help            show this help message and exit
      --project PROJECT
      --auth                Authenticate to Github (increases rate limits)
      --label-needs-work LABEL_NEEDS_WORK
      --label-needs-decision LABEL_NEEDS_DECISION
      --label-needs-champion LABEL_NEEDS_CHAMPION
      --label-needs-backport LABEL_NEEDS_BACKPORT
      
Results for `SciPy`_ and `NumPy`_ are provided on an ad-hoc basis at
https://pav.iki.fi/scipy-needs-work/ and https://pav.iki.fi/numpy-needs-work/

.. _SciPy: https://github.com/scipy/scipy
.. _NumPy: https://github.com/numpy/numpy
