\# SteadyLink MultiSim



\*\*Multi-protocol GPS / DSM simulator and playback tool\*\*



MultiSim replays recorded DSM telemetry logs and outputs them in multiple serial protocols used for antenna tracking, broadcast telemetry, and navigation systems.



Originally developed for the \*\*TS-D tracking platform\*\*, but designed to be a standalone diagnostic and integration tool.



---



\# ✨ Features



\* Replay DSM log files with preserved timing

\* Multiple serial output protocols:



&nbsp; \* AMP (binary)

&nbsp; \* Kenwood

&nbsp; \* DSM passthrough

&nbsp; \* NMEA (GPGGA / GPRMC / GSA / GSV)

&nbsp; \* LiveTools burst

&nbsp; \* PKLDS legacy protocol

\* Optional mirror outputs (DSM + NMEA simultaneously)

\* Start replay at specific timestamp

\* Loop playback

\* DSM filtering and validation options

\* Optional HTTP GPS API server for TS-D Live

\* Multi-vehicle simulation support



---



\# 📦 Requirements



Python 3.9+



Install dependencies:



```bash

pip install pyserial

```



---



\# 🚀 Basic Usage



```bash

python multisim.py <input\_file> --port COM9 --protocol AMP19200

```



Example:



```bash

python multisim.py sim.txt --port COM9 --protocol AMP19200

```



---



\# 🧭 Supported Protocol Modes



| Mode          | Baud   | Description                          |

| ------------- | ------ | ------------------------------------ |

| AMP19200      | 19200  | AMP binary protocol                  |

| KENWOOD4800   | 4800   | Kenwood binary protocol              |

| DSM115200     | 115200 | Raw DSM passthrough                  |

| GPGGA4800     | 4800   | NMEA GPGGA output                    |

| LIVETOOLS4800 | 4800   | Full NMEA burst (GGA, GSA, GSV, RMC) |

| PKLDS9600     | 9600   | Legacy PKLDS protocol                |



---



\# 📄 Input File



The input file must contain DSM log lines:



```

\[timestamp]DSMxx,HHMMSS,lat,lon,alt,speed,course,status

```



Example:



```

\[123456]DSM00,105704,50.12345,4.56789,120.0,30.5,180.0,0F

```



---



\# 🔧 Arguments Overview



\## Required



\### `<input\_file>`



DSM log file to replay.



Example:



```bash

sim-error-on105704.txt

```



---



\## Serial Output



\### `--port <COM>`



Main serial output port.



Example:



```bash

--port COM9

```



---



\### `--protocol <MODE>`



Output protocol on the main port.



Available modes:



```

AMP19200

KENWOOD4800

DSM115200

GPGGA4800

LIVETOOLS4800

PKLDS9600

```



Example:



```bash

--protocol AMP19200

```



---



\## Optional Outputs



\### `--DSM-out <COM>`



Mirror raw DSM output at \*\*115200 baud\*\*.



Example:



```bash

--DSM-out COM8

```



---



\### `--nmea-out <COM>`



Mirror NMEA output at \*\*4800 baud\*\* (DSM00 only).



Sequence:



1\. GPRMC

2\. wait 200 ms

3\. GPGGA



Example:



```bash

--nmea-out COM10

```



---



\## Filtering Options



\### `--ignore <DSMxx>`



Ignore one or more DSM IDs.



Can be repeated.



Example:



```bash

--ignore DSM00 --ignore DSM01

```



---



\### `--require-0F`



Only process DSM lines with status byte `0F`.



Example:



```bash

--require-0F

```



---



\### `--id <DSMxx>`



DSM ID filter used only with \*\*GPGGA4800\*\* mode.



Example:



```bash

--id DSM00

```



---



\## Tracking Options



\### `--enable-remapDSM00`



Remap DSM00 to ID `0x64` (100 decimal) for AMP / Kenwood tracking systems.



---



\## Playback Control



\### `--loop`



Restart playback automatically when end of file is reached.



---



\### `--starttime HHMMSS`



Start replay at or after a given time.



Example:



```bash

--starttime 120000

```



---



\## HTTP Server



\### `--enable-server`



Starts a local HTTP server for TS-D Live integration.



Default port: \*\*5005\*\*



Example:



```bash

--enable-server

```



Custom port:



```bash

--enable-server --server-port 6000

```



API endpoints:



```

GET /ping

GET /api/sources

```



---



\# 🧪 Example Full Command



```bash

python multisim.py sim.txt ^

&nbsp;   --port COM9 ^

&nbsp;   --protocol AMP19200 ^

&nbsp;   --DSM-out COM8 ^

&nbsp;   --nmea-out COM10 ^

&nbsp;   --enable-remapDSM00 ^

&nbsp;   --enable-server

```



---



\# 🛰 PKLDS Output



PKLDS mode generates legacy sentences:



```

92 <ETX> <STX> $PKLDS,,A,ddmm.mmmm,N,dddmm.mmmm,E,,,,,E00,100,VID,80,00,\*CS

```



Baud: \*\*9600\*\*



---



\# 🌐 HTTP API Example



```

http://localhost:5005/api/sources

```



Response:



```json

{

&nbsp; "sources": \[

&nbsp;   {

&nbsp;     "id": 0,

&nbsp;     "lat": 50.123,

&nbsp;     "lng": 4.456,

&nbsp;     "heading": 180,

&nbsp;     "speed": 35,

&nbsp;     "altitude": 120,

&nbsp;     "lastUpdateUtc": "/Date(1712345678900)/"

&nbsp;   }

&nbsp; ]

}

```



---



\# 👨‍💻 Author



\*\*Jens Vanhoof\*\*

SteadyLink / WorldLinX



---



\# 📜 License



Private / Internal Use (adjust as needed)



