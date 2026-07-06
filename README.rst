Python module for near field communication
==========================================

The **nfcpy** module implements NFC Forum specifications for wireless short-range data exchange with NFC devices and tags. It is written in Python and aims to provide an easy-to-use yet powerful framework for applications integrating NFC.

This repository is a customized version updated to support the **Sony RC-S300 (PaSoRi)** reader/writer.

🚀 Quick Start (RC-S300 Support)
---------------------------------

If you want to use the Sony RC-S300, you can install this version directly via ``pip``::

    pip install git+https://github.com/ajinori-256/nfcpy.git

Hardware Support Status for RC-S300
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **FeliCa:** **Supported** (Verified to work with communication and ID reading)
* **ISO/IEC 14443 Type A/B:** *Under development / coming soon*

About This Repository
---------------------

* **License:** EUPL_
* **Original Project:** GitHub_
* **Documentation:** `Read the Docs`_ (Refer to the original documentation for general API usage)

.. _Python: https://www.python.org
.. _EUPL: https://joinup.ec.europa.eu/software/page/eupl
.. _GitHub: https://github.com/nfcpy/nfcpy
.. _Read the Docs: https://nfcpy.readthedocs.org/