REM multisim.py sim.txt  --enable-server --starttime 152900 --port COM21 --protocol DSM115200  --nmea-out COM10 --enable-remapDSM00 --loop



py multisim.py dsm_20260315.txt --port COM2 --protocol DSM115200 --loop --starttime 131427
pause

REM ------------------------------------------------------------
REM multisim.py arguments overview
REM ------------------------------------------------------------
REM
REM <input_file>
REM   DSM log file to replay
REM   Example: sim-error-on105704.txt
REM
REM --port <COM>
REM   Main serial output port (AMP / DSM / GPGGA depending on protocol)
REM   Example: --port COM9
REM
REM --protocol <MODE>
REM   Output protocol on --port
REM   Modes: AMP19200 | KENWOOD4800 | DSM115200 | GPGGA4800
REM   Example: --protocol AMP19200
REM
REM --DSM-out <COM>
REM   Optional mirror output of raw DSM at 115200 baud
REM   Example: --DSM-out COM8
REM
REM --nmea-out <COM>
REM   Optional NMEA output at 4800 baud (DSM00 only)
REM   Outputs: GPRMC, wait 200 ms, then GPGGA
REM   Example: --nmea-out COM10
REM
REM --ignore <DSMxx>
REM   Ignore one or more DSM IDs (can be repeated)
REM   Example: --ignore DSM00 --ignore DSM01
REM
REM --require-0F
REM   Only process DSM lines with status byte 0F
REM   Example: --require-0F
REM
REM --id <DSMxx>
REM   DSM ID filter (used only with GPGGA4800 mode)
REM   Example: --id DSM00
REM
REM --enable-remapDSM00
REM Remap DSM00 to ID 100 for the tracking (0x64)
REM
REM --loop
REM At the end of the data file, restart.

REM --starttime 120000 
REM start immediately at $DSMxx,120000 (HHMMSS)
REM Example full command:
REM python multisim.py sim.txt --port COM9 --protocol AMP19200 --DSM-out COM8 --nmea-out COM10  --enable-remapDSM00
REM
REM --enable-server
REM starts server on port 5005 for use with TS-D Live
REM ------------------------------------------------------------
