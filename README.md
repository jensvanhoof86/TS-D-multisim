# SteadyLink MultiSim

**Multi-protocol GPS / DSM simulator and playback tool**

MultiSim replays recorded DSM telemetry logs and outputs them in multiple serial protocols used for antenna tracking, broadcast telemetry, and navigation systems.

Originally developed for the **TS-D tracking platform**, but designed to be a standalone diagnostic and integration tool.

---

# ✨ Features

* Replay DSM log files with preserved timing

* Multiple serial output protocols:

  * AMP (binary)
  * Kenwood
  * DSM passthrough
  * NMEA (GPGGA / GPRMC / GSA / GSV)
  * LiveTools burst
  * PKLDS legacy protocol

* Optional mirror outputs (DSM + NMEA simultaneously)

* Start replay at specific timestamp

* Loop playback

* DSM filtering and validation options

* Console highlighting of specific DSM IDs, each in its own colour

* Optional HTTP GPS API server for TS-D Live

* LiveTools TCP broadcast server

* Serial datastream TCP mirror

* Multi-vehicle simulation support

---

# 📦 Requirements

Python 3.9+

Install dependencies:

```bash
pip install pyserial
```

---

# 🚀 Basic Usage

```bash
python multisim.py <input_file> --port COM9 --protocol AMP19200
```

Example:

```bash
python multisim.py sim.txt --port COM9 --protocol AMP19200
```

---

# 🧭 Supported Protocol Modes

| Mode          | Baud   | Description                          |
| ------------- | ------ | ------------------------------------ |
| AMP19200      | 19200  | AMP binary protocol                  |
| KENWOOD4800   | 4800   | Kenwood binary protocol              |
| DSM115200     | 115200 | Raw DSM passthrough                  |
| GPGGA4800     | 4800   | NMEA GPGGA output                    |
| LIVETOOLS4800 | 4800   | Full NMEA burst (GGA, GSA, GSV, RMC) |
| PKLDS9600     | 9600   | Legacy PKLDS protocol                |
| NMEA4800      | 4800   | GPRMC, wait 200ms, then GPGGA        |
| PRAVE115200   | 115200 | Raveon $PRAVE sentence (AN177)       |

---

# 📄 Input File

The input file must contain DSM log lines:

```
[timestamp]DSMxx,HHMMSS,lat,lon,alt,speed,course,status
```

Example:

```
[123456]DSM00,105704,50.12345,4.56789,120.0,30.5,180.0,0F
```

---

# 🔧 Arguments Overview

## Required

### `<input_file>`

DSM log file to replay.

Example:

```bash
sim-error-on105704.txt
```

---

## Serial Output

### `--port <COM>`

Main serial output port.

Example:

```bash
--port COM9
```

---

### `--protocol <MODE>`

Output protocol on the main port.

Available modes:

```
AMP19200
KENWOOD4800
DSM115200
GPGGA4800
LIVETOOLS4800
PKLDS9600
NMEA4800
PRAVE115200
```

Example:

```bash
--protocol AMP19200
```

---

### `--override-baudrate <BAUD>`

Override the baud rate used to open `--port`, regardless of the protocol's default.

Example:

```bash
--protocol AMP19200 --override-baudrate 9600
```

---

## Optional Outputs

### `--DSM-out <COM>`

Mirror raw DSM output at **115200 baud**.

Example:

```bash
--DSM-out COM8
```

---

### `--nmea-out <COM>`

Mirror NMEA output at **4800 baud** (DSM00 only).

Sequence:

1. GPRMC
2. wait 200 ms
3. GPGGA

Example:

```bash
--nmea-out COM10
```

---

# 🌐 TCP Streaming Options

## `--enable-datastream`

Mirrors **all data sent to the main serial port** to a TCP server.

Port:

```
10012
```

Works with **any protocol mode**.

Useful for:

* Network debugging
* Feeding virtual receivers
* Recording output streams
* Integration testing

Example:

```bash
--enable-datastream
```

Connect:

```
localhost:10012
```

---

## `--enable-livetools-server`

Starts a TCP server that broadcasts **LiveTools NMEA bursts**.

Port:

```
10013
```

Behavior:

* Identical data format to `LIVETOOLS4800` mode
* Works even if main protocol is different
* Uses DSM ID filtering (`--id`)
* Does not interfere with serial timing

Example:

```bash
--enable-livetools-server --id DSM00
```

Connect:

```
localhost:10013
```

---

## Filtering Options

### `--ignore <DSMxx>`

Ignore one or more DSM IDs.

Can be repeated.

Example:

```bash
--ignore DSM00 --ignore DSM01
```

---

### `--require-0F`

Only process DSM lines with status byte `0F`.

Example:

```bash
--require-0F
```

---

### `--id <DSMxx>`

DSM ID filter used with:

* GPGGA4800
* LIVETOOLS4800
* NMEA4800
* LiveTools TCP server

Example:

```bash
--id DSM00
```

---

### `--highlight <DSMxx>`

Highlight one or more DSM IDs in the console output so they stand out from the rest of the log. Each highlighted ID gets its own distinct colour (cycled if you list more than 6). Doesn't filter or drop any lines — purely a display aid.

Can be repeated and/or comma-separated.

Example:

```bash
--highlight DSM01 --highlight DSM03
```

```bash
--highlight DSM01,DSM03
```

---

## Tracking Options

### `--enable-remapDSM00`

Remap DSM00 to ID `0x64` (100 decimal) for AMP / Kenwood tracking systems.

---

### `--prave-id-map <path.json>`

Only used with `--protocol PRAVE115200`. Optional JSON file mapping DSM hex IDs to the numeric "From ID" sent in the `$PRAVE` sentence.

Format:

```json
{
  "00": 1000,
  "0B": 1001
}
```

If omitted, `prave_id_map.json` next to `multisim.py` is used if present; otherwise a built-in default is used:

| DSM ID | PRAVE From ID |
| ------ | -------------- |
| DSM00  | 1000            |
| DSM0B  | 1001            |
| DSM0C  | 1002            |
| DSM0D  | 1003            |
| DSM03  | 1006            |

Any DSM ID not listed in the map falls back to its raw hex value (e.g. DSM0A → 10) so the protocol still works for unmapped vehicles. Edit the JSON file (or point `--prave-id-map` at a different one) to change the mapping without touching code.

Example:

```bash
--protocol PRAVE115200 --prave-id-map my_prave_ids.json
```

---

### `--prave-strict-map`

Only affects `PRAVE115200`. Any DSM ID **not** present in the PRAVE ID map is skipped entirely (no `$PRAVE` sentence sent for it), instead of falling back to its raw hex value.

Example:

```bash
--protocol PRAVE115200 --prave-strict-map
```

---

## Playback Control

### `--loop`

Restart playback automatically when end of file is reached.

---

### `--starttime HHMMSS`

Start replay at or after a given time.

Example:

```bash
--starttime 120000
```

---

## HTTP Server

### `--enable-server`

Starts a local HTTP server for TS-D Live integration.

Default port: **5005**

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

# 🧪 Example Full Command

```bash
python multisim.py sim.txt ^
    --port COM9 ^
    --protocol AMP19200 ^
    --DSM-out COM8 ^
    --nmea-out COM10 ^
    --enable-remapDSM00 ^
    --enable-server ^
    --enable-datastream ^
    --enable-livetools-server --id DSM00
```

---

# 🛰 PKLDS Output

PKLDS mode generates legacy sentences:

```
92 <ETX> <STX> $PKLDS,,A,ddmm.mmmm,N,dddmm.mmmm,E,,,,,E00,100,VID,80,00,*CS
```

Baud: **9600**

Vehicle ID:

```
1000 + DSM hex ID
```

Example:

```
DSM0A → 1010
```

---

# 📡 PRAVE Output

PRAVE mode generates Raveon `$PRAVE` sentences (see `AN177 (PRAVE).pdf`):

```
$PRAVE,FromID,ToID,lat,lon,hhmmss,gpsStatus,numSats,alt,temp,voltage,ioStatus,rssi,speed,heading,status,spare*CS
```

Baud: **115200** (default; override with `--override-baudrate` if your radio uses a different rate, e.g. the AN177 native rate of 38400)

* `FromID` comes from the DSM hex ID via the [PRAVE ID map](#--prave-id-map-pathjson)
* `ToID` is always `0000` (simulator doesn't model a destination)
* Latitude/longitude use signed `ddmm.mmmm` / `dddmm.mmmm` (no separate N/S/E/W field)
* Speed is converted from the log's knots to km/h as required by the spec
* Satellite count, temperature, voltage, IO status and RSSI are simulated with fixed placeholder values since the DSM log doesn't carry them

---

# 🌐 HTTP API Example

```
http://localhost:5005/api/sources
```

Response:

```json
{
  "sources": [
    {
      "id": 0,
      "lat": 50.123,
      "lng": 4.456,
      "heading": 180,
      "speed": 35,
      "altitude": 120,
      "lastUpdateUtc": "/Date(1712345678900)/"
    }
  ]
}
```

---

# 👨‍💻 Author

**Jens Vanhoof**
SteadyLink / WorldLinX

---

# 📜 License

Private / Internal Use (adjust as needed)
