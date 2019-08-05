=================
github-needs-work
=================

::

    usage: github_needs_work.py

    Print pull requests in Github which have needs-work label despite
    having updated commits. Creates a cache file ``gh_cache.json`` in the
    current directory. The script also understands Github PR review and
    draft statuses, and interprets "changes requested" as "needs-work".

    examples:
      github_needs_work.py --auth --project scipy/scipy < token > out.html

    optional arguments:
      -h, --help            show this help message and exit
      --project PROJECT     project to use (e.g. scipy/scipy)
      --auth                authenticate to Github (increases rate limits)
      --label-needs-work LABEL_NEEDS_WORK
                            name of the label for 'needs-work' status (default:
                            needs-work)
      --label-needs-decision LABEL_NEEDS_DECISION
                            name of the label for 'needs-decision' status
                            (default: needs-decision)
      --label-needs-champion LABEL_NEEDS_CHAMPION
                            name of the label for 'needs-champion' status
                            (default: needs-champion)
      --label-needs-backport LABEL_NEEDS_BACKPORT
                            name of the label for 'needs-backport' status
                            (default: backport-candidate)
      
Results for `SciPy`_ and `NumPy`_ are provided on an ad-hoc basis at
https://pav.iki.fi/scipy-needs-work/ and https://pav.iki.fi/numpy-needs-work/

.. _SciPy: https://github.com/scipy/scipy
.. _NumPy: https://github.com/numpy/numpy
