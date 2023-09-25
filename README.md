[![Python Versions](https://img.shields.io/badge/python-3.10%20%7C%203.11-blue)](https://github.com/awsr/rstats-logger)

# Warning

It appears that the time reported through Python is UTC instead of the time zone the router was configured for. Currently working on either a reliable way to get the actual time, or will remove the cutoff timestamps.

## rstats

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
