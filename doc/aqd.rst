Processing Aquadopp (currents) data
***********************************

After getting the code, make sure you change ``sys.path`` or ``sys.path.append`` lines point to the equivalent place on the local system.

**NOTE: this code works with up- or down-looking Aquadopp data collected in 'beam', 'XYZ' or 'earth'. 
It doesn't work on HR AQD yet.**

Data will generally be processed using a series of run scripts that use command line arguments.  For AQD currents it's a 2 step process.

Step 1 : Instrument data to raw .cdf
=====================================

Step 1 : Convert from text to a raw netCDF file with ``.cdf`` extension using runaqdhdr2cdf.py. This script
depends on two arguments, the global attribute file and extra configuration information :doc:`configuration files </config>`.

runaqdhdr2cdf.py
----------------

.. argparse::
   :ref: stglib.core.cmd.aqdhdr2cdf_parser
   :prog: runaqdhdr2cdf.py

Step 2 : Convert the raw .cdf to clean, EPIC format .nc using runaqdcdf2nc.py.
==============================================================================

Convert the raw .cdf data into an EPIC-compliant netCDF file with .nc extension, optionally including :doc:`atmospheric correction </atmos>` of the pressure data.  Correcting pressure for atmospheric is a side-bar task- use the .ipynb examples to see what to do.

runaqdcdf2nc.py
---------------

.. argparse::
   :ref: stglib.core.cmd.aqdcdf2nc_parser
   :prog: runaqdcdf2nc.py
