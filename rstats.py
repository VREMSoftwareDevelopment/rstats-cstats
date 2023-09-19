#!/usr/bin/python
#
# reference rstats.c TomatoUsb source code
#
#
#    Copyright (C) 2010 - 2015 VREM Software Development <VREMSoftwareDevelopment@gmail.com>
#    Copyright (C) 2023 Alex Wiser <https://github.com/awsr>
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.
#

# IMPORTANT: Currently designed to run as a CRON job on the router every hour.
#            Script makes several assumptions based on this expectation.

import argparse
import gzip
import json
import math
import struct
import sys
import traceback
from datetime import datetime, timedelta
from datetime import date as dt_date
from datetime import time as dt_time
from os.path import isfile, getmtime
from shutil import copyfile


# Pre-calculate for performance
PETABYTE = math.pow(1024, 5)
DATE_FORMAT = "%Y-%m-%d"
TIME_FORMAT = "%H:%M"
NOW = datetime.now()
YESTERDAY = NOW.date() - timedelta(days=1)
ONE_HOUR_AGO_TIME = (NOW - timedelta(hours=1)).time()


def default(obj):
    if isinstance(obj, dt_date):
        return obj.strftime(DATE_FORMAT)
    if isinstance(obj, dt_time):
        return obj.strftime(TIME_FORMAT)
    if isinstance(obj, Comment):
        return {
            "message": obj.message,
            "cutoff_down": obj.cutoff_down,
            "cutoff_up": obj.cutoff_up,
        }
    raise TypeError(f"Unable to serialize {obj} of type {type(obj)}")


class Comment:
    def __init__(
        self,
        cutoff_down: str | None = None,
        cutoff_up: str | None = None,
        message: str | None = None,
    ):
        super().__init__()
        if message is None:
            self.message = "Data error. Values are lower than actual."
        else:
            self.message = message
        self.cutoff_down = cutoff_down
        self.cutoff_up = cutoff_up

    @property
    def cutoff_down(self) -> str | None:
        return self._cutoff_down

    @cutoff_down.setter
    def cutoff_down(self, new_cutoff: dt_date | str | None):
        if isinstance(new_cutoff, dt_date):
            self._cutoff_down = new_cutoff.strftime(TIME_FORMAT)
        else:
            self._cutoff_down = new_cutoff

    @property
    def cutoff_up(self) -> str | None:
        return self._cutoff_up

    @cutoff_up.setter
    def cutoff_up(self, new_cutoff: dt_date | str | None):
        if isinstance(new_cutoff, dt_date):
            self._cutoff_up = new_cutoff.strftime(TIME_FORMAT)
        else:
            self._cutoff_up = new_cutoff


class Props:  # pylint: disable=too-few-public-methods
    def __init__(
        self, date: dt_date | str, down: int, up: int, comment: dict | None = None
    ):
        if isinstance(date, str):
            date = datetime.strptime(date, DATE_FORMAT).date()
        self.date = date
        self.down = down
        self.up = up
        self.comment = None if comment is None else Comment(**comment)


class DataPoint(dict):
    # fmt: off
    _data_scale = {
        'kb': 1, 'kib': 1,
        'mb': 2, 'mib': 2,
        'gb': 3, 'gib': 3,
        'tb': 4, 'tib': 4,
        'pb': 5, 'pib': 5,
        'eb': 6, 'eib': 6
    }
    _data_scale_names = ('B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB')
    # fmt: on

    def __init__(self, props: Props, daily=False):
        super().__init__()
        self["date"] = props.date
        self["down"] = -1 if props.down > PETABYTE else props.down
        self["up"] = -1 if props.up > PETABYTE else props.up
        # Include comments only if necessary
        if props.comment is not None:
            self["comment"] = props.comment
        # Set error comments if data is invalid
        if self["down"] == -1:
            self.note_error(daily, True)
        if self["up"] == -1:
            self.note_error(daily, False)

    @staticmethod
    def format_bytes(size: int, scale: str = None) -> str:
        if size < 1024:
            return f"{size} B"

        scale = scale.lower()

        if scale is None or scale not in DataPoint._data_scale:
            exponent = int(math.floor(math.log(size, 1024)))
        else:
            exponent = DataPoint._data_scale[scale]

        divisor = math.pow(1024, exponent)
        value = round(size / divisor, 2)
        return f"{value} {DataPoint._data_scale_names[exponent]}"

    @property
    def date_string(self) -> str:
        return self["date"].strftime(DATE_FORMAT)

    @property
    def total_bytes(self) -> int:
        return self["down"] + self["up"]

    def note_error(
        self,
        is_daily: bool = False,
        is_down: bool = False,
        msg: str | None = None,
    ):
        """Make note of error and set last known good data time, if applicable"""
        if "comment" not in self:
            self["comment"] = Comment(message=msg)

        if is_daily:
            if self["date"] >= YESTERDAY:
                # Error happened yesterday or today
                if is_down:
                    self["comment"].cutoff_down = ONE_HOUR_AGO_TIME
                else:
                    self["comment"].cutoff_up = ONE_HOUR_AGO_TIME
            # Else: Somehow even older data got corrupted,
            # but it can be fully restored and all values will be overwritten
        else:
            # Monthly comments don't use timestamps
            self["comment"].message = msg

    def __str__(self) -> str:
        return (
            f"{self['date'].strftime(DATE_FORMAT)}: "
            + f"{DataPoint.format_bytes(self['down'])}, "
            + f"{DataPoint.format_bytes(self['up'])}"
        )


class StatsData:
    def __init__(self) -> None:
        super().__init__()
        self.daily: dict = {}
        self.monthly: dict = {}

    def add_daily(self, entry):
        new_data = DataPoint(Props(*entry), daily=True)
        self.daily[new_data.date_string] = new_data

    def add_monthly(self, entry):
        new_data = DataPoint(Props(*entry))
        self.monthly[new_data.date_string] = new_data

    def merge_history(self, previous_data):
        # Previous data uses default types
        if "daily" in previous_data:
            for previous in previous_data["daily"]:
                prev_date = previous["date"]
                if prev_date is None:
                    continue
                # Use old data to fill in history and roll back errors
                if prev_date in self.daily:
                    self._update_handler(self.daily[prev_date], previous)
                else:
                    self.daily[prev_date] = DataPoint(Props(**previous), True)

        if "monthly" in previous_data:
            for previous in previous_data["monthly"]:
                prev_date = previous["date"]
                if prev_date is None:
                    continue
                # Use old data to fill in history and roll back errors
                if prev_date in self.monthly:
                    self._update_handler(self.monthly[prev_date], previous)
                else:
                    self.monthly[prev_date] = DataPoint(Props(**previous))

    def _update_handler(self, curr: DataPoint, prev: dict):
        # Previous data uses default types
        if "comment" in prev:
            if "comment" not in curr:
                curr["comment"] = Comment(**prev["comment"])
            else:
                # Use merge in old data, if available
                curr["comment"].message = prev["comment"]["message"]
                if (
                    "cutoff_down" in prev["comment"]
                    and prev["comment"]["cutoff_down"] is not None
                ):
                    curr["comment"].cutoff_down = prev["comment"]["cutoff_down"]
                if (
                    "cutoff_up" in prev["comment"]
                    and prev["comment"]["cutoff_up"] is not None
                ):
                    curr["comment"].cutoff_up = prev["comment"]["cutoff_up"]

        # Set to highest value (invalid data would already be set to -1)
        curr["down"] = max(curr["down"], prev["down"])
        curr["up"] = max(curr["up"], prev["up"])


# rstats supports version ID_V1
class RStats:
    # expected file size in bytes
    EXPECTED_SIZE = 2112
    # version 0 has 12 entries per month
    ID_V0 = 0x30305352
    # version1 has 25 entries per month
    ID_V1 = 0x31305352

    MONTH_COUNT = 25
    DAY_COUNT = 62

    def __init__(self, filename: str):
        try:
            print(">>>>>>>>>> Tomato USB RSTATS <<<<<<<<<<")
            if filename.endswith("gz"):
                with gzip.open(filename, "rb") as file_handle:
                    self.file_content = file_handle.read()
            else:
                with open(filename, "rb") as file_handle:
                    self.file_content = file_handle.read()

            if len(self.file_content) != RStats.EXPECTED_SIZE:
                print(
                    "Unsupported File Format. Require unzip file size: "
                    + f"{RStats.EXPECTED_SIZE}."
                )
                sys.exit(2)
            print(f"Supported File Format Version: {RStats.ID_V1}")
            self.index = 0
            self.data = StatsData()
        except IOError:
            sys.stderr.write("Can NOT read file: " + filename)
            traceback.print_exc()

    def dump(self):
        self._version_check()

        for entry_d in self._dump_stats(RStats.DAY_COUNT):
            self.data.add_daily(entry_d)
        self._unpack_value("q", 8)

        for entry_m in self._dump_stats(RStats.MONTH_COUNT):
            self.data.add_monthly(entry_m)
        self._unpack_value("q", 8)

        self._completion_check()
        return self.data

    def print(self):
        self._version_check()

        print("---------- Daily ----------")
        self.print_stats(RStats.DAY_COUNT)
        print(f"dailyp: {self._unpack_value('q', 8)}")

        print("---------- Monthly ----------")
        self.print_stats(RStats.MONTH_COUNT)
        print(f"monthlyp: {self._unpack_value('q', 8)}")

        self._completion_check()

    def print_stats(self, size):
        print("Date (yyyy-mm-dd),Down (bytes),Up (bytes)")
        for stat in self._dump_stats(size):
            print(f"{stat[0].strftime(DATE_FORMAT)},{stat[1]},{stat[2]}")

    def _dump_stats(self, size):
        for _ in range(size):
            time = self._unpack_value("Q", 8)
            down = self._unpack_value("Q", 8)
            up = self._unpack_value("Q", 8)
            date = self.get_date(time)
            if date.year > 1900:
                yield (date, down, up)

    def _unpack_value(self, unpack_type, size):
        current = self.index
        self.index += size
        if self.index > RStats.EXPECTED_SIZE:
            sys.stderr.write(
                f"Reached end of the buffer. {self.index}/{RStats.EXPECTED_SIZE}"
            )
            sys.exit(3)
        (value,) = struct.unpack(unpack_type, self.file_content[current : self.index])
        return value

    def _version_check(self):
        """Check file format version"""
        version = self._unpack_value("Q", 8)
        print(f"Version: {version}")
        if version != RStats.ID_V1:
            sys.stderr.write(f"Unknown version number: {version}\n")
            sys.exit(2)

    def _completion_check(self):
        """Check if all bytes are read"""
        if self.index == self.EXPECTED_SIZE:
            print("All bytes read")
        else:
            print(">>> Warning!")
            print(f"Read {self.index} bytes.")
            print(f"Expected to read {RStats.EXPECTED_SIZE} bytes.")
            print(f"Left to read {RStats.EXPECTED_SIZE - self.index} bytes")

    @staticmethod
    def get_date(time):
        year = ((time >> 16) & 0xFF) + 1900
        month = ((time >> 8) & 0xFF) + 1
        day = time & 0xFF
        return dt_date(year, month, 1 if day == 0 else day)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("filename")
    parser.add_argument("-o", "--out")

    args = parser.parse_args()

    if isfile(args.filename):
        modified = datetime.fromtimestamp(getmtime(args.filename))
        if args.out is None:
            RStats(args.filename).print()
        else:
            stats = RStats(args.filename).dump()
            if isfile(args.out):
                copyfile(args.out, f"{args.out}.bak")
                try:
                    with open(args.out, "r", encoding="utf8") as f:
                        prev_export = json.loads(f.read())
                    stats.merge_history(prev_export)
                except json.JSONDecodeError as err:
                    sys.stderr.write("JSON Decode Error: " + err.msg)
                    copyfile(args.out, f"{args.out}.err")

            export_object = {}
            export_object["meta"] = {
                "time_data": modified.isoformat(),
                "time_script": NOW.isoformat(),
            }
            export_object["daily"] = sorted(
                list(stats.daily.values()), key=lambda entry: entry["date"]
            )
            export_object["monthly"] = sorted(
                list(stats.monthly.values()), key=lambda entry: entry["date"]
            )
            json_data = json.dumps(export_object, default=default)
            with open(args.out, "w", encoding="utf8") as f:
                f.write(json_data)

            copyfile(args.filename, f"{args.filename}.bak")

    else:
        parser.exit(1, f"{args.filename} not found")


if __name__ == "__main__":
    main()
