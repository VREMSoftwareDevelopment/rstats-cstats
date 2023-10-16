[![Python Versions](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://github.com/awsr/rstats-logger)

# rstats

- Reads rstats file backup bandwidth usage file created by Tomato USB (router firmware), Asuswrt-Merlin, and others.
- Displays human readable format to console.
- Logs traffic stats to a JSON file.
- Attempts to gracefully handle instances of a bug with ASUS RT-AC68U where values will get corrupted and show up as being in the exabyte range.

### Usage:
`python rstats.py <filename> [--out <output-filename>]`

### Examples:

#### Print to console:

`python rstats.py tomato_rstats.gz`

#### Log to file:

`python rstats.py tomato_rstats.gz --out traffic.json`

---

### Warning

Python seems to be told the system time is in UTC instead of what the router is set to... except in some circumstances. For reliability, the system's `date` command is used to get time values. If this fails, cutoff timestamps for data errors will not be available.
